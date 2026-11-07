import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import launcher  # noqa: E402

GIT_BASH = "C:\\Program Files\\Git\\bin\\bash.exe"
WT = "C:\\Users\\x\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe"
WIN_ENV = {"EXEPATH": "C:\\Program Files\\Git", "LOCALAPPDATA": "C:\\Users\\x\\AppData\\Local"}
TMUX = "/usr/bin/tmux"
CLAUDE = "/home/x/.local/bin/claude"


class Completed:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


class Runner:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or Completed()
        self.error = error

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if self.error:
            raise self.error
        return self.result


class TmuxRunner:
    """A fake subprocess.run for tmux: answers has-session and the window command separately."""

    def __init__(self, session_exists=True, result=None, error=None, has_session_error=None):
        self.calls = []
        self.kwargs = []
        self.session_exists = session_exists
        self.result = result or Completed()
        self.error = error
        self.has_session_error = has_session_error

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        self.kwargs.append(kwargs)
        if cmd[1] == "has-session":
            if self.has_session_error:
                raise self.has_session_error
            return Completed(0 if self.session_exists else 1, "" if self.session_exists else "no session")
        if self.error:
            raise self.error
        return self.result

    def window_calls(self):
        return [cmd for cmd in self.calls if cmd[1] != "has-session"]


def which_from(found):
    return lambda name: found.get(name)


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def windows(self, env=None, runner=None, now=None, isfile=None, which=None):
        self.runner = runner or Runner()
        return launcher.WindowsBackend(
            self.state, env=WIN_ENV if env is None else env,
            # which("bash") would find System32's WSL shim, which must never be used.
            which=which or which_from({"wt.exe": WT, "claude": "C:\\bin\\claude.exe",
                                       "bash": "C:\\Windows\\System32\\bash.exe"}),
            isfile=isfile or (lambda p: p == GIT_BASH), runner=self.runner, now=now or time.time)

    def launcher_files(self):
        folder = os.path.join(self.state, "launchers")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def launcher_text(self):
        return (Path(self.state) / "launchers" / self.launcher_files()[0]).read_text(encoding="utf-8")

    def test_should_detect_the_backend(self):
        cases = [
            ("auto", {"WSL_DISTRO_NAME": "Ubuntu"}, "posix", "wsl"),
            ("auto", {"WSL_DISTRO_NAME": "Ubuntu", "MSYSTEM": "MINGW64"}, "nt", "wsl"),
            ("auto", {}, "nt", "windows"),
            ("auto", {"MSYSTEM": "MINGW64"}, "posix", "windows"),
            ("auto", {}, "posix", "tmux"),
            ("windows", {"WSL_DISTRO_NAME": "Ubuntu"}, "posix", "windows"),
            ("wsl", {}, "nt", "wsl"),
            ("tmux", {"WSL_DISTRO_NAME": "Ubuntu"}, "nt", "tmux"),
        ]
        for choice, env, os_name, expected in cases:
            backend = launcher.detect(choice, env, os_name, self.state)
            self.assertEqual(backend.name, expected, (choice, env, os_name))

    def test_should_choose_wsl_then_windows_then_tmux_automatically(self):
        self.assertEqual(launcher.auto_choice({"WSL_DISTRO_NAME": "Ubuntu", "MSYSTEM": "MINGW64"}, "nt"), "wsl")
        self.assertEqual(launcher.auto_choice({}, "nt"), "windows")
        self.assertEqual(launcher.auto_choice({"MSYSTEM": "MINGW64"}, "posix"), "windows")
        self.assertEqual(launcher.auto_choice({}, "posix"), "tmux")
        self.assertEqual(launcher.auto_choice({"WSL_DISTRO_NAME": ""}, "posix"), "tmux")

    def test_should_refuse_an_unknown_launcher(self):
        with self.assertRaisesRegex(launcher.LaunchError, "unknown launcher 'mac'"):
            launcher.detect("mac", {}, "posix", self.state)

    def test_should_open_a_named_window_with_git_bash_from_exepath(self):
        backend = self.windows()
        backend.open_tab("Rev PR#12 acme/widgets", "C:/Users/x/GitHub", ["claude", "-n", "t"])
        cmd = self.runner.calls[0]
        self.assertEqual(cmd[:7], [WT, "-w", "review-watcher", "new-tab", "--title", "Rev PR#12 acme/widgets",
                                   "--suppressApplicationTitle"])
        self.assertEqual(cmd[7:9], ["-d", "C:\\Users\\x\\GitHub"])
        self.assertEqual(cmd[9:12], ["--", GIT_BASH, "--login"])
        self.assertTrue(cmd[12].endswith(".sh"))
        self.assertEqual(cmd.count("-w"), 1)
        self.assertNotIn("C:\\Windows\\System32\\bash.exe", cmd)

    def test_should_leave_an_unpinned_title_to_the_program(self):
        backend = self.windows()
        backend.open_tab("Rev PR#12 acme/widgets", "C:/x", ["claude"], pin_title=False)
        cmd = self.runner.calls[0]
        self.assertEqual(cmd[3:8], ["new-tab", "--title", "Rev PR#12 acme/widgets", "--useApplicationTitle", "-d"])
        self.assertNotIn("--suppressApplicationTitle", cmd)
        self.wsl().open_tab("Rev PR#3 acme/gadgets", "/home/x", ["claude"], pin_title=False)
        self.assertEqual(self.runner.calls[0][3:8], ["new-tab", "--title", "Rev PR#3 acme/gadgets",
                                                     "--useApplicationTitle", "wsl.exe"])

    def test_should_pin_the_title_explicitly_by_default(self):
        self.windows().open_tab("t", "C:/x", ["claude"])
        cmd = self.runner.calls[0]
        self.assertIn("--suppressApplicationTitle", cmd)
        self.assertNotIn("--useApplicationTitle", cmd)

    def test_should_prefer_the_configured_git_bash_path(self):
        env = dict(WIN_ENV, CLAUDE_CODE_GIT_BASH_PATH="D:\\Git\\bin\\bash.exe")
        backend = self.windows(env=env, isfile=lambda p: True)
        self.assertEqual(backend.git_bash(), "D:\\Git\\bin\\bash.exe")

    def test_should_write_a_clean_launcher_script(self):
        backend = self.windows()
        argv = ["python3", "C:/p/orchestrator.py", "run", "--title", "a b'c"]
        backend.open_tab("Review Watcher", "C:\\Users\\x\\GitHub", argv)
        names = self.launcher_files()
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("review-watcher-"), names[0])
        raw = (Path(self.state) / "launchers" / names[0]).read_bytes()
        self.assertNotIn(b"\r", raw)
        lines = raw.decode("utf-8").split("\n")
        self.assertEqual(lines[0], "#!/bin/bash")
        self.assertTrue(lines[1].startswith("unset CLAUDECODE CLAUDE_CODE_CHILD_SESSION"))
        self.assertIn("CLAUDE_JOB_DIR", lines[1])
        self.assertEqual(lines[2], "cd /c/Users/x/GitHub || "
                                   "{ echo 'review-watcher: cannot open the session directory'; exec bash -l -i; }")
        self.assertEqual(lines[3], "MSYS_NO_PATHCONV=1 python3 C:/p/orchestrator.py run --title 'a b'\"'\"'c'")
        self.assertEqual(lines[4], "exec bash -l -i")

    def test_should_not_keep_the_shell_open_when_asked_not_to(self):
        self.windows().open_tab("t", "C:/x", ["claude"], keep_open=False)
        raw = self.launcher_text()
        self.assertNotIn("exec bash", raw)
        self.assertIn("cannot open the session directory'; exit 1; }", raw)

    def test_should_add_no_model_or_effort_flag_unless_configured(self):
        self.assertEqual(launcher.claude_argv("T", "C:/p.md", None, None),
                         ["claude", "-n", "T", "Read C:/p.md and follow it exactly."])
        self.assertEqual(launcher.claude_argv("T", "C:/p.md", "opus", "high"),
                         ["claude", "-n", "T", "--model", "opus", "--effort", "high",
                          "Read C:/p.md and follow it exactly."])

    def test_should_explain_a_missing_git_bash(self):
        backend = self.windows(isfile=lambda p: False)
        with self.assertRaisesRegex(launcher.LaunchError, "Git Bash.*CLAUDE_CODE_GIT_BASH_PATH"):
            backend.open_tab("t", "C:/x", ["claude"])
        self.assertEqual(self.runner.calls, [])
        self.assertTrue(any("Git Bash" in p for p in backend.problems()))

    def test_should_refuse_a_title_wt_would_interpret_before_running_anything(self):
        backend = self.windows()
        with self.assertRaisesRegex(launcher.LaunchError, "interpret"):
            backend.open_tab("bad; title", "C:/x", ["claude"])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.launcher_files(), [])

    def test_should_report_a_wt_failure(self):
        backend = self.windows(runner=Runner(Completed(1, "no window")))
        with self.assertRaisesRegex(launcher.LaunchError, "wt.exe failed: no window"):
            backend.open_tab("t", "C:/x", ["claude"])
        backend = self.windows(runner=Runner(error=OSError("not found")))
        with self.assertRaisesRegex(launcher.LaunchError, "wt.exe could not be run") as caught:
            backend.open_tab("t", "C:/x", ["claude"])
        self.assertNotIsInstance(caught.exception, launcher.LaunchTimeout)

    def test_should_report_a_wt_timeout_as_uncertain(self):
        backend = self.windows(runner=Runner(error=subprocess.TimeoutExpired("wt", 30)))
        with self.assertRaisesRegex(launcher.LaunchTimeout, "wt.exe did not exit .*may have opened"):
            backend.open_tab("t", "C:/x", ["claude"])

    def test_should_sweep_only_launchers_older_than_a_day(self):
        folder = os.path.join(self.state, "launchers")
        os.makedirs(folder)
        old, fresh = os.path.join(folder, "old.sh"), os.path.join(folder, "fresh.sh")
        other = os.path.join(folder, "notes.txt")
        for path in (old, fresh, other):
            open(path, "w").close()
        aged = time.time() - 2 * 24 * 60 * 60
        os.utime(old, (aged, aged))
        os.utime(other, (aged, aged))
        self.windows().open_tab("t", "C:/x", ["claude"])
        remaining = self.launcher_files()
        self.assertNotIn("old.sh", remaining)
        self.assertIn("fresh.sh", remaining)
        self.assertIn("notes.txt", remaining)
        self.assertEqual(len(remaining), 3)

    def test_should_report_windows_problems(self):
        backend = self.windows(which=which_from({}), isfile=lambda p: False)
        self.assertEqual(len(backend.problems()), 3)
        self.assertEqual(self.windows().problems(), [])

    # --- wsl ---------------------------------------------------------------------------------

    def wsl(self, runner=None):
        self.runner = runner or Runner()
        return launcher.WslBackend(self.state, env={"WSL_DISTRO_NAME": "Ubuntu"},
                                   which=which_from({"wt.exe": "/mnt/c/wt.exe", "claude": "/usr/bin/claude"}),
                                   runner=self.runner)

    def test_should_run_the_wsl_tab_through_a_launcher_script(self):
        argv = launcher.claude_argv("Rev PR#3 acme/gadgets", "/home/x/p.md", None, None)
        self.wsl().open_tab("Rev PR#3 acme/gadgets", "/home/x/GitHub", argv)
        cmd = self.runner.calls[0]
        self.assertEqual(cmd[:15], [
            "wt.exe", "-w", "review-watcher", "new-tab", "--title", "Rev PR#3 acme/gadgets",
            "--suppressApplicationTitle", "wsl.exe", "-d", "Ubuntu", "--cd", "/home/x/GitHub", "--", "bash",
            "--login"])
        names = self.launcher_files()
        self.assertEqual(len(names), 1)
        self.assertTrue(cmd[15].endswith("/launchers/" + names[0]))
        lines = self.launcher_text().split("\n")
        self.assertTrue(lines[1].startswith("unset CLAUDECODE CLAUDE_CODE_CHILD_SESSION"))
        self.assertEqual(lines[2], "cd /home/x/GitHub || "
                                   "{ echo 'review-watcher: cannot open the session directory'; exec bash -l -i; }")
        self.assertEqual(lines[3], "/usr/bin/claude -n 'Rev PR#3 acme/gadgets' "
                                   "'Read /home/x/p.md and follow it exactly.'")
        self.assertEqual(lines[4], "exec bash -l -i")

    def test_should_close_the_wsl_tab_only_when_asked_not_to_keep_it_open(self):
        self.wsl().open_tab("t", "/home/x", ["claude"], keep_open=False)
        text = self.launcher_text()
        self.assertNotIn("exec bash", text)
        self.assertIn("cannot open the session directory'; exit 1; }", text)

    def test_should_refuse_unsafe_wsl_arguments_and_report_wsl_problems(self):
        backend = self.wsl()
        with self.assertRaisesRegex(launcher.LaunchError, "interpret"):
            backend.open_tab("t", "/home/x;y", ["claude"])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.launcher_files(), [])
        empty = launcher.WslBackend(self.state, env={}, which=which_from({}), runner=self.runner)
        self.assertEqual(len(empty.problems()), 3)

    def test_should_refuse_a_wsl_tab_when_claude_is_missing(self):
        backend = launcher.WslBackend(self.state, env={"WSL_DISTRO_NAME": "Ubuntu"},
                                      which=which_from({"wt.exe": "/mnt/c/wt.exe"}), runner=Runner())
        with self.assertRaisesRegex(launcher.LaunchError, "claude was not found"):
            backend.open_tab("t", "/home/x", ["claude"])
        self.assertEqual(self.launcher_files(), [])

    # --- tmux --------------------------------------------------------------------------------

    def tmux(self, runner=None, found=None):
        self.runner = runner or TmuxRunner()
        return launcher.TmuxBackend(self.state, which=which_from({"tmux": TMUX, "claude": CLAUDE} if found is None
                                                                 else found),
                                    runner=self.runner)

    def test_should_add_a_detached_window_when_the_session_exists(self):
        argv = launcher.claude_argv("Rev PR#3 acme/gadgets", "/home/x/p.md", None, None)
        self.tmux(TmuxRunner(session_exists=True)).open_tab("Rev PR#3 acme/gadgets", "/home/x/GitHub", argv)
        self.assertEqual(self.runner.calls[0], [TMUX, "has-session", "-t", "=review-watcher"])
        names = self.launcher_files()
        self.assertEqual(len(names), 1)
        cmd = self.runner.calls[1]
        self.assertEqual(cmd[:12], [TMUX, "new-window", "-d", "-t", "=review-watcher:", "-n", "Rev PR#3 acme/gadgets",
                                    "-c", "/home/x/GitHub", "bash", "--login",
                                    os.path.join(self.state, "launchers", names[0])])
        self.assertEqual(len(cmd), 12)
        self.assertEqual(len(self.runner.calls), 2)
        self.assertEqual(self.runner.kwargs[1]["timeout"], launcher.RUN_TIMEOUT_SECONDS)

    def test_should_start_a_detached_session_when_none_exists(self):
        self.tmux(TmuxRunner(session_exists=False)).open_tab("Review Watcher", "/home/x/GitHub", ["claude"])
        self.assertEqual(self.runner.calls[0][1], "has-session")
        names = self.launcher_files()
        self.assertEqual(self.runner.calls[1], [TMUX, "new-session", "-d", "-s", "review-watcher", "-n",
                                                "Review Watcher", "-c", "/home/x/GitHub", "bash", "--login",
                                                os.path.join(self.state, "launchers", names[0])])
        self.assertNotIn("new-window", [c[1] for c in self.runner.calls])

    def test_should_replace_a_bare_claude_with_its_full_path_in_the_tmux_script(self):
        argv = launcher.claude_argv("Rev PR#3 acme/gadgets", "/home/x/p.md", "opus", None)
        self.tmux().open_tab("Rev PR#3 acme/gadgets", "/home/x/GitHub", argv)
        lines = self.launcher_text().split("\n")
        self.assertTrue(lines[1].startswith("unset CLAUDECODE CLAUDE_CODE_CHILD_SESSION"))
        self.assertEqual(lines[2], "cd /home/x/GitHub || "
                                   "{ echo 'review-watcher: cannot open the session directory'; exec bash -l -i; }")
        self.assertEqual(lines[3], f"{CLAUDE} -n 'Rev PR#3 acme/gadgets' --model opus "
                                   "'Read /home/x/p.md and follow it exactly.'")
        self.assertEqual(lines[4], "exec bash -l -i")

    def test_should_leave_a_command_that_is_not_claude_alone(self):
        self.tmux().open_tab("Review Watcher", "/home/x", ["python3", "/p/orchestrator.py", "run"])
        self.assertEqual(self.launcher_text().split("\n")[3], "python3 /p/orchestrator.py run")

    def test_should_close_the_tmux_window_only_when_asked_not_to_keep_it_open(self):
        self.tmux().open_tab("t", "/home/x", ["claude"], keep_open=False)
        text = self.launcher_text()
        self.assertNotIn("exec bash", text)
        self.assertIn("cannot open the session directory'; exit 1; }", text)

    def test_should_refuse_unsafe_tmux_arguments_before_running_tmux(self):
        for title, cwd in (("t", "/home/x;y"), ("bad'title", "/home/x"), ("t", "/home/$HOME"),
                           ("t", "C:\\work"), ("t", "/home/x`id`")):
            for exists in (True, False):
                backend = self.tmux(TmuxRunner(session_exists=exists))
                with self.assertRaisesRegex(launcher.LaunchError, "refuses", msg=(title, cwd)):
                    backend.open_tab(title, cwd, ["claude"])
                self.assertEqual(self.runner.calls, [], (title, cwd))
                self.assertEqual(self.launcher_files(), [], (title, cwd))

    def test_should_refuse_a_tmux_tab_when_tmux_is_missing(self):
        backend = self.tmux(found={"claude": CLAUDE})
        with self.assertRaisesRegex(launcher.LaunchError, "tmux was not found on PATH"):
            backend.open_tab("t", "/home/x", ["claude"])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.launcher_files(), [])
        self.assertEqual(backend.problems(), ["tmux was not found on PATH; the tmux launcher needs it"])

    def test_should_refuse_a_tmux_tab_when_claude_is_missing(self):
        backend = self.tmux(found={"tmux": TMUX})
        with self.assertRaisesRegex(launcher.LaunchError, "claude was not found on PATH"):
            backend.open_tab("t", "/home/x", ["claude"])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.launcher_files(), [])
        self.assertEqual(backend.problems(), ["claude was not found on PATH"])

    def test_should_report_no_tmux_problems_when_everything_is_found(self):
        self.assertEqual(self.tmux().problems(), [])
        self.assertEqual(len(self.tmux(found={}).problems()), 2)

    def test_should_report_a_tmux_failure(self):
        backend = self.tmux(TmuxRunner(result=Completed(1, "create window failed")))
        with self.assertRaisesRegex(launcher.LaunchError, "tmux failed: create window failed"):
            backend.open_tab("t", "/home/x", ["claude"])
        backend = self.tmux(TmuxRunner(error=OSError("exec format error")))
        with self.assertRaisesRegex(launcher.LaunchError, "tmux could not be run") as caught:
            backend.open_tab("t", "/home/x", ["claude"])
        self.assertNotIsInstance(caught.exception, launcher.LaunchTimeout)

    def test_should_report_a_tmux_timeout_as_uncertain(self):
        backend = self.tmux(TmuxRunner(error=subprocess.TimeoutExpired("tmux", 30)))
        with self.assertRaisesRegex(launcher.LaunchTimeout, "tmux did not exit .*may have opened"):
            backend.open_tab("t", "/home/x", ["claude"])

    def test_should_open_nothing_when_has_session_cannot_run(self):
        for error in (OSError("permission denied"), subprocess.TimeoutExpired("tmux", 30)):
            backend = self.tmux(TmuxRunner(has_session_error=error))
            with self.assertRaisesRegex(launcher.LaunchError, "tmux could not be run") as caught:
                backend.open_tab("t", "/home/x", ["claude"])
            self.assertNotIsInstance(caught.exception, launcher.LaunchTimeout)
            self.assertEqual(self.runner.window_calls(), [])
            self.assertEqual(self.launcher_files(), [])

    def test_should_check_tmux_working_directories_with_the_plain_character_set(self):
        backend = self.tmux()
        self.assertIs(backend.safe_cwd, launcher.WSL_SAFE)
        self.assertEqual(backend.name, "tmux")
        self.assertEqual(backend.session, "review-watcher")

    def test_should_resolve_claude_only_for_a_bare_claude(self):
        which = which_from({"claude": CLAUDE})
        self.assertEqual(launcher.resolve_claude(["claude", "-n", "t"], which), [CLAUDE, "-n", "t"])
        self.assertEqual(launcher.resolve_claude(["/opt/claude", "x"], which), ["/opt/claude", "x"])
        self.assertEqual(launcher.resolve_claude([], which), [])
        original = ["claude"]
        launcher.resolve_claude(original, which)
        self.assertEqual(original, ["claude"])
        with self.assertRaisesRegex(launcher.LaunchError, "claude was not found"):
            launcher.resolve_claude(["claude"], which_from({}))


if __name__ == "__main__":
    unittest.main()
