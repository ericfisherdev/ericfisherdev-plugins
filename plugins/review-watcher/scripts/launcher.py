"""Open a terminal tab or window for the watcher and for each review session.

Three backends: Windows (Git Bash inside a named Windows Terminal window), WSL (Windows Terminal
running wsl.exe) and tmux (windows in a detached tmux session, for Linux and macOS). Every
argument that reaches wt.exe or tmux is checked against a plain character set first, because
wt.exe reads `;` as a command separator and the shells behind it would interpret quotes, `$` and `&`.
"""

import ntpath
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from config import native_path

WINDOW = "review-watcher"
RUN_TIMEOUT_SECONDS = 30
LAUNCHER_MAX_AGE_SECONDS = 24 * 60 * 60
WIN_SAFE = re.compile(r"^[A-Za-z0-9._/\\+:=@ #-]+$")
WSL_SAFE = re.compile(r"^[A-Za-z0-9._/+:=@ #-]+$")
# A session spawned from the poller must not believe it is a child of another Claude session.
CLEARED_ENV = ("CLAUDECODE CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_SESSION_ID CLAUDE_CODE_ENTRYPOINT "
               "CLAUDE_CODE_EXECPATH AI_AGENT CLAUDE_EFFORT CLAUDE_JOB_DIR")
DRIVE = re.compile(r"^([A-Za-z]):[\\/]*(.*)$")


class LaunchError(Exception):
    pass


class LaunchTimeout(LaunchError):
    """The terminal command did not exit in time, so the tab may or may not be open."""


def claude_argv(title, prompt_file, model, effort, claude="claude"):
    """The command a session tab runs. A model or effort that is not configured adds no flag."""
    argv = [claude, "-n", title]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    argv.append(f"Read {prompt_file} and follow it exactly.")
    return argv


def posix_path(value):
    """C:\\x\\y -> /c/x/y for use inside a Git Bash script."""
    match = DRIVE.match(value)
    if match:
        return "/" + match.group(1).lower() + "/" + match.group(2).replace("\\", "/")
    return value.replace("\\", "/")


def slug(title):
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower() or "tab"


class Backend:
    """Every backend runs the tab through a generated bash script, so `keep_open` and the cleared
    environment do not depend on the terminal's profile."""

    name = ""
    # The rule open_tab applies to a tab's working directory, so a worktree it would refuse falls back early.
    safe_cwd = WIN_SAFE
    # Prepended to the command; Git Bash would otherwise rewrite /-prefixed arguments into Windows paths.
    command_prefix = ""

    def __init__(self, state_dir, now=time.time, runner=subprocess.run):
        self.launchers = Path(state_dir) / "launchers"
        self.now = now
        self.runner = runner

    def problems(self):
        """Readable reasons this backend cannot open tabs here; [] when it can."""
        raise NotImplementedError("Backend subclasses must implement problems()")

    def open_tab(self, title, cwd, argv, keep_open=True, pin_title=True):
        """Open one tab titled `title` in `cwd` running `argv`. Raises LaunchError or LaunchTimeout."""
        raise NotImplementedError("Backend subclasses must implement open_tab()")

    def script_cwd(self, cwd):
        return cwd

    def launcher_path(self, title):
        return self.launchers / f"{slug(title)}-{int(self.now() * 1000)}.sh"

    def sweep(self):
        cutoff = self.now() - LAUNCHER_MAX_AGE_SECONDS
        try:
            for path in self.launchers.glob("*.sh"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue
        except OSError:
            return

    def script(self, cwd, argv, keep_open):
        # A failed cd must never fall through to the command, which would run in the wrong checkout.
        on_cd_failure = "exec bash -l -i" if keep_open else "exit 1"
        lines = [
            "#!/bin/bash",
            f"unset {CLEARED_ENV}",
            f"cd {shlex.quote(self.script_cwd(cwd))} || "
            f"{{ echo 'review-watcher: cannot open the session directory'; {on_cd_failure}; }}",
            self.command_prefix + " ".join(shlex.quote(arg) for arg in argv),
        ]
        if keep_open:
            lines.append("exec bash -l -i")
        return "\n".join(lines) + "\n"

    def write_script(self, launcher, cwd, argv, keep_open):
        self.sweep()
        self.launchers.mkdir(parents=True, exist_ok=True)
        with open(launcher, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(self.script(cwd, argv, keep_open))

    def run_terminal(self, cmd, label):
        """Run the terminal command; raises LaunchTimeout when it hangs and LaunchError when it fails."""
        try:
            result = self.runner(cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as err:
            raise LaunchTimeout(f"{label} did not exit within {RUN_TIMEOUT_SECONDS}s; the tab may have opened") from err
        except OSError as err:
            raise LaunchError(f"{label} could not be run: {err}") from err
        if result.returncode != 0:
            detail = (result.stderr or "").strip() or f"exit {result.returncode}"
            raise LaunchError(f"{label} failed: {detail}")


def resolve_claude(argv, which):
    """argv with a bare `claude` replaced by its full path: the tab's login shell may have another PATH."""
    argv = list(argv)
    if argv and argv[0] == "claude":
        claude = which("claude")
        if not claude:
            raise LaunchError("claude was not found on PATH")
        argv[0] = claude
    return argv


def title_args(title, pin_title):
    """A pinned title ignores the program's own title updates, which carry Claude Code's status icon.

    Both cases pass a flag: omitting one falls back to the profile's suppressApplicationTitle setting.
    """
    return ["--title", title, "--suppressApplicationTitle" if pin_title else "--useApplicationTitle"]


class WindowsBackend(Backend):
    name = "windows"
    command_prefix = "MSYS_NO_PATHCONV=1 "

    def __init__(self, state_dir, env=None, which=shutil.which, isfile=os.path.isfile,
                 runner=subprocess.run, now=time.time):
        super().__init__(state_dir, now, runner)
        self.env = os.environ if env is None else env
        self.which = which
        self.isfile = isfile

    def git_bash(self):
        env = self.env
        candidates = []
        if env.get("CLAUDE_CODE_GIT_BASH_PATH"):
            candidates.append(env["CLAUDE_CODE_GIT_BASH_PATH"])
        if env.get("EXEPATH"):
            candidates.append(ntpath.join(env["EXEPATH"], "bin", "bash.exe"))
        if env.get("LOCALAPPDATA"):
            candidates.append(ntpath.join(env["LOCALAPPDATA"], "Programs", "Git", "bin", "bash.exe"))
        if env.get("ProgramFiles"):
            candidates.append(ntpath.join(env["ProgramFiles"], "Git", "bin", "bash.exe"))
        for path in candidates:
            if self.isfile(path):
                return path
        raise LaunchError("Git Bash (bash.exe) not found; install Git for Windows or set CLAUDE_CODE_GIT_BASH_PATH")

    def problems(self):
        found = []
        if not self.which("wt.exe"):
            found.append("wt.exe was not found on PATH; tabs need Windows Terminal")
        try:
            self.git_bash()
        except LaunchError as err:
            found.append(str(err))
        if not self.which("claude"):
            found.append("claude was not found on PATH")
        return found

    def script_cwd(self, cwd):
        return posix_path(cwd)

    def open_tab(self, title, cwd, argv, keep_open=True, pin_title=True):
        bash = self.git_bash()
        launcher = self.launcher_path(title)
        cmd = [self.which("wt.exe") or "wt.exe", "-w", WINDOW, "new-tab", *title_args(title, pin_title),
               "-d", native_path(cwd, "nt"), "--", bash, "--login", native_path(str(launcher), "nt")]
        unsafe = [arg for arg in cmd if not WIN_SAFE.match(arg)]
        if unsafe:
            raise LaunchError("an argument has a character that wt.exe would interpret (only letters, digits, "
                              f"spaces and . _ / \\ + : = @ # - are allowed): {unsafe[0]}")
        self.write_script(launcher, cwd, argv, keep_open)
        self.run_terminal(cmd, "wt.exe")


class WslBackend(Backend):
    name = "wsl"
    safe_cwd = WSL_SAFE

    def __init__(self, state_dir, env=None, which=shutil.which, runner=subprocess.run, now=time.time):
        super().__init__(state_dir, now, runner)
        self.env = os.environ if env is None else env
        self.which = which

    def problems(self):
        found = []
        if not self.env.get("WSL_DISTRO_NAME"):
            found.append("WSL_DISTRO_NAME is not set; tabs need Windows Terminal on WSL")
        if not self.which("wt.exe"):
            found.append("wt.exe was not found on PATH; tabs need Windows Terminal on WSL")
        if not self.which("claude"):
            found.append("claude was not found on PATH")
        return found

    def open_tab(self, title, cwd, argv, keep_open=True, pin_title=True):
        distro = self.env.get("WSL_DISTRO_NAME", "")
        if not distro:
            raise LaunchError("WSL_DISTRO_NAME is not set; tabs need Windows Terminal on WSL")
        if not self.which("wt.exe"):
            raise LaunchError("wt.exe was not found on PATH; tabs need Windows Terminal on WSL")
        argv = resolve_claude(argv, self.which)
        launcher = self.launcher_path(title)
        cmd = ["wt.exe", "-w", WINDOW, "new-tab", *title_args(title, pin_title),
               "wsl.exe", "-d", distro, "--cd", cwd, "--", "bash", "--login", launcher.as_posix()]
        # wsl.exe hands the arguments after `--` to a shell, so only a plain character set may reach it.
        unsafe = [arg for arg in cmd if not WSL_SAFE.match(arg)]
        if unsafe:
            raise LaunchError("an argument has a character that wt.exe or the shell behind wsl.exe would "
                              "interpret (only letters, digits, spaces and . _ / + : = @ # - are allowed): "
                              f"{unsafe[0]}")
        self.write_script(launcher, cwd, argv, keep_open)
        self.run_terminal(cmd, "wt.exe")


class TmuxBackend(Backend):
    """Each tab is a window in the detached tmux session `review-watcher`; `tmux attach -t review-watcher` shows them."""

    name = "tmux"
    safe_cwd = WSL_SAFE
    session = WINDOW

    def __init__(self, state_dir, which=shutil.which, runner=subprocess.run, now=time.time):
        super().__init__(state_dir, now, runner)
        self.which = which

    def problems(self):
        found = []
        if not self.which("tmux"):
            found.append("tmux was not found on PATH; the tmux launcher needs it")
        if not self.which("claude"):
            found.append("claude was not found on PATH")
        return found

    def session_exists(self, tmux):
        try:
            result = self.runner([tmux, "has-session", "-t", f"={self.session}"], capture_output=True, text=True,
                                 timeout=RUN_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as err:
            raise LaunchError(f"tmux could not be run: {err}") from err
        return result.returncode == 0

    def open_tab(self, title, cwd, argv, keep_open=True, pin_title=True):
        """Naming the window with -n turns off tmux's automatic rename, so `pin_title` needs no flag."""
        tmux = self.which("tmux")
        if not tmux:
            raise LaunchError("tmux was not found on PATH; the tmux launcher needs it")
        argv = resolve_claude(argv, self.which)
        launcher = self.launcher_path(title)
        # Several arguments after the options run directly, without `sh -c`.
        shell = ["bash", "--login", launcher.as_posix()]
        unsafe = [arg for arg in [tmux, title, cwd, *shell] if not WSL_SAFE.match(arg)]
        if unsafe:
            raise LaunchError("an argument has a character the launcher refuses (only letters, digits, spaces and "
                              f". _ / + : = @ # - are allowed): {unsafe[0]}")
        if self.session_exists(tmux):
            # -d keeps an attached client on the window it is showing.
            cmd = [tmux, "new-window", "-d", "-t", f"={self.session}:", "-n", title, "-c", cwd, *shell]
        else:
            cmd = [tmux, "new-session", "-d", "-s", self.session, "-n", title, "-c", cwd, *shell]
        self.write_script(launcher, cwd, argv, keep_open)
        self.run_terminal(cmd, "tmux")


def auto_choice(env, os_name):
    if env.get("WSL_DISTRO_NAME"):
        return "wsl"
    if os_name == "nt" or env.get("MSYSTEM"):
        return "windows"
    return "tmux"


def detect(choice, env, os_name, state_dir, which=shutil.which, runner=subprocess.run, **windows_kwargs):
    """The backend for `launcher` = auto|windows|wsl|tmux. Raises LaunchError for an unknown choice."""
    if choice == "auto":
        choice = auto_choice(env, os_name)
    if choice == "wsl":
        return WslBackend(state_dir, env=env, which=which, runner=runner)
    if choice == "windows":
        return WindowsBackend(state_dir, env=env, which=which, runner=runner, **windows_kwargs)
    if choice == "tmux":
        return TmuxBackend(state_dir, which=which, runner=runner)
    raise LaunchError(f"unknown launcher '{choice}'")
