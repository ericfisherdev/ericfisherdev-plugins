import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config  # noqa: E402
import launcher  # noqa: E402
import workdir  # noqa: E402
from fake_gh import FakeGh  # noqa: E402
from gh_client import GhClient  # noqa: E402

HUB = "/hub"
REPO = "acme/widgets"
MAIN = os.path.join(HUB, "widgets")
MODES = ("clone", "root")


def porcelain(*records):
    """Build `git worktree list --porcelain -z` output from (path, branch) pairs.

    A branch of "bare" makes a bare record and None a detached one.
    """
    out = ""
    for path, branch in records:
        out += f"worktree {path}\0"
        if branch == "bare":
            out += "bare\0"
        elif branch is None:
            out += "HEAD 0123456789abcdef\0detached\0"
        else:
            out += f"HEAD 0123456789abcdef\0branch refs/heads/{branch}\0"
        out += "\0"
    return out


class FakeGit:
    def __init__(self, out="", rc=0, err=""):
        self.result = (rc, out, err)
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        return self.result


def gh_for(head="feature/x", cross=False, rc=0):
    fake = FakeGh().on("pr view", {"headRefName": head, "isCrossRepository": cross}, rc=rc, stderr="boom")
    return fake, GhClient(runner=fake)


class ParseWorktreesTest(unittest.TestCase):
    def test_should_parse_every_record_kind_ending_in_a_double_nul(self):
        text = (
            "worktree /hub/widgets\0HEAD aaa\0branch refs/heads/main\0\0"
            "worktree /work/wt-x\0HEAD bbb\0branch refs/heads/feature/x\0locked a reason\0\0"
            "worktree /work/wt-d\0HEAD ccc\0detached\0\0"
            "worktree /work/wt-p\0HEAD ddd\0branch refs/heads/old\0prunable gitdir file points to non-existent\0\0"
            "worktree /hub/bare\0bare\0\0"
        )
        self.assertTrue(text.endswith("\0\0"))
        self.assertEqual(workdir.parse_worktrees(text), [
            ("/hub/widgets", "refs/heads/main", False),
            ("/work/wt-x", "refs/heads/feature/x", False),
            ("/work/wt-d", None, False),
            ("/work/wt-p", "refs/heads/old", False),
            ("/hub/bare", None, True),
        ])

    def test_should_parse_empty_output_and_a_missing_terminator(self):
        self.assertEqual(workdir.parse_worktrees(""), [])
        self.assertEqual(workdir.parse_worktrees("worktree /a\0branch refs/heads/b"),
                         [("/a", "refs/heads/b", False)])


class RunGitTest(unittest.TestCase):
    def test_should_pass_the_args_through_and_return_the_streams(self):
        seen = {}

        def run(cmd, **kwargs):
            seen["cmd"], seen["kwargs"] = cmd, kwargs
            return subprocess.CompletedProcess(cmd, 3, stdout="out", stderr="err")

        self.assertEqual(workdir.run_git(["-C", "x", "status"], run=run), (3, "out", "err"))
        self.assertEqual(seen["cmd"], ["git", "-C", "x", "status"])
        self.assertEqual(seen["kwargs"]["timeout"], workdir.GIT_TIMEOUT_SECONDS)
        self.assertEqual(seen["kwargs"]["encoding"], "utf-8")

    def test_should_drop_inherited_git_location_variables_from_the_child_env(self):
        seen = {}

        def run(cmd, **kwargs):
            seen["env"] = kwargs["env"]
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        environ = {name: "/elsewhere" for name in workdir.GIT_LOCATION_VARS}
        environ.update(PATH="/bin", GIT_TERMINAL_PROMPT="0")
        workdir.run_git(["status"], run=run, environ=environ)
        self.assertEqual(seen["env"], {"PATH": "/bin", "GIT_TERMINAL_PROMPT": "0"})

    def test_should_clear_git_location_variables_in_place(self):
        environ = {name: "/elsewhere" for name in workdir.GIT_LOCATION_VARS}
        environ["PATH"] = "/bin"
        workdir.clear_git_location(environ)
        self.assertEqual(environ, {"PATH": "/bin"})

    def test_should_turn_a_missing_git_into_rc_1(self):
        def run(cmd, **kwargs):
            raise FileNotFoundError("git")

        rc, out, err = workdir.run_git(["status"], run=run)
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("git", err)

    def test_should_turn_a_timeout_into_rc_1(self):
        def run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 20)

        self.assertEqual(workdir.run_git(["status"], run=run)[0], 1)


class ChooseTest(unittest.TestCase):
    def choose(self, git, gh, repo=REPO, dirs=(), files=None, fallback="clone", os_name="posix",
               environ=None, isdir=None):
        files = {os.path.join(MAIN, ".git")} if files is None else set(files)
        dirs = {MAIN, *dirs}
        return workdir.choose(HUB, repo, 7, gh, git,
                              isdir=isdir or (lambda p: p in dirs),
                              exists=lambda p: p in files or p in dirs,
                              fallback=fallback, os_name=os_name, environ=environ or {})

    def fallback_dir(self, mode):
        return HUB if mode == "root" else MAIN

    def test_should_return_the_worktree_on_the_pr_branch_in_both_modes(self):
        for mode in MODES:
            fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
            cwd, problem = self.choose(git, gh, dirs={"/work/wt-x"}, fallback=mode)
            self.assertEqual((cwd, problem), (config.native_path("/work/wt-x"), None), mode)
            self.assertEqual(git.calls, [["-C", MAIN, "worktree", "list", "--porcelain", "-z"]])
            self.assertEqual(fake.calls[0][0], "pr view 7 -R acme/widgets --json headRefName,isCrossRepository")

    def test_should_skip_a_missing_worktree_directory_without_a_note(self):
        for mode in MODES:
            _fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "main"), ("/work/gone", "feature/x")))
            self.assertEqual(self.choose(git, gh, fallback=mode), (self.fallback_dir(mode), None), mode)

    def test_should_take_the_first_usable_match(self):
        _fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), ("/work/gone", "feature/x"), ("/work/wt-2", "feature/x")))
        self.assertEqual(self.choose(git, gh, dirs={"/work/wt-2"})[0], config.native_path("/work/wt-2"))

    def test_should_fall_back_when_only_other_or_detached_branches_exist(self):
        for mode in MODES:
            _fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "main"), ("/work/a", "feature/y"), ("/work/b", None)))
            got = self.choose(git, gh, dirs={"/work/a", "/work/b"}, fallback=mode)
            self.assertEqual(got, (self.fallback_dir(mode), None), mode)

    def test_should_refuse_a_path_the_launcher_would_refuse(self):
        _fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), ("/work/wt (x)", "feature/x")))
        cwd, problem = self.choose(git, gh, dirs={"/work/wt (x)"})
        self.assertEqual(cwd, MAIN)
        self.assertEqual(problem, "worktree /work/wt (x) has characters the launcher refuses")

    def test_should_refuse_a_path_the_selected_launcher_would_refuse(self):
        path = "/work/wt\\x"
        _fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), (path, "feature/x")))
        dirs = {MAIN, path}
        common = dict(isdir=lambda p: p in dirs, exists=lambda p: p in dirs or p == os.path.join(MAIN, ".git"),
                      os_name="posix", environ={})
        self.assertEqual(workdir.choose(HUB, REPO, 7, gh, git, **common)[0],
                         config.native_path(path))
        _fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), (path, "feature/x")))
        cwd, problem = workdir.choose(HUB, REPO, 7, gh, git, safe_cwd=launcher.WSL_SAFE, **common)
        self.assertEqual((cwd, problem), (MAIN, f"worktree {path} has characters the launcher refuses"))

    def test_should_check_the_other_platform_before_the_directory(self):
        calls = []

        def isdir(path):
            calls.append(path)
            return path == MAIN

        cases = [("nt", {}, "/mnt/c/work/wt-x"), ("posix", {"WSL_DISTRO_NAME": "Ubuntu"}, "C:/work/wt-x")]
        for os_name, environ, path in cases:
            _fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "main"), (path, "feature/x")))
            cwd, problem = self.choose(git, gh, os_name=os_name, environ=environ, isdir=isdir)
            self.assertEqual(cwd, MAIN)
            self.assertEqual(problem, f"worktree {path} is not reachable from this platform")
            self.assertNotIn(path, calls)

    def test_should_not_treat_a_drive_path_as_foreign_outside_wsl(self):
        _fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), ("C:/work/wt-x", "feature/x")))
        cwd, problem = self.choose(git, gh, dirs={"C:/work/wt-x"})
        self.assertEqual((cwd, problem), (config.native_path("C:/work/wt-x"), None))

    def test_should_fall_back_with_a_note_when_git_fails(self):
        for mode in MODES:
            fake, gh = gh_for()
            git = FakeGit(rc=128, err="fatal: detected dubious ownership")
            cwd, problem = self.choose(git, gh, fallback=mode)
            self.assertEqual(cwd, self.fallback_dir(mode))
            self.assertIn("git worktree list failed: fatal: detected dubious ownership", problem)
            self.assertEqual(fake.calls, [])

    def test_should_fall_back_with_a_note_when_gh_fails(self):
        for mode in MODES:
            _fake, gh = gh_for(rc=1)
            git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
            cwd, problem = self.choose(git, gh, dirs={"/work/wt-x"}, fallback=mode)
            self.assertEqual(cwd, self.fallback_dir(mode))
            self.assertTrue(problem.startswith("could not read the head branch: "), problem)

    def test_should_fall_back_when_the_gh_runner_raises_an_os_error(self):
        def runner(args, input=None):
            raise PermissionError("denied")

        git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
        cwd, problem = self.choose(git, GhClient(runner=runner), dirs={"/work/wt-x"})
        self.assertEqual(cwd, MAIN)
        self.assertIn("denied", problem)

    def test_should_fall_back_when_gh_prints_bad_json(self):
        fake = FakeGh().on("pr view", "{not json")
        git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
        cwd, problem = self.choose(git, GhClient(runner=fake), dirs={"/work/wt-x"})
        self.assertEqual(cwd, MAIN)
        self.assertTrue(problem.startswith("could not read the head branch"))

    def test_should_fall_back_on_an_unexpected_gh_response(self):
        for body in ([], {"isCrossRepository": False}, {"headRefName": ""}):
            fake = FakeGh().on("pr view", body)
            git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
            cwd, problem = self.choose(git, GhClient(runner=fake), dirs={"/work/wt-x"})
            self.assertEqual(cwd, MAIN, body)
            self.assertEqual(problem, "could not read the head branch: unexpected response", body)

    def test_should_ignore_a_same_named_branch_of_a_fork_pr(self):
        for mode in MODES:
            _fake, gh = gh_for(cross=True)
            git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
            got = self.choose(git, gh, dirs={"/work/wt-x"}, fallback=mode)
            self.assertEqual(got, (self.fallback_dir(mode), None), mode)

    def test_should_skip_gh_when_the_registry_has_one_record(self):
        for mode in MODES:
            fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "feature/x")))
            self.assertEqual(self.choose(git, gh, fallback=mode), (self.fallback_dir(mode), None), mode)
            self.assertEqual(fake.count("pr view"), 0)

    def test_should_skip_gh_when_there_is_no_client(self):
        git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
        self.assertEqual(self.choose(git, None, dirs={"/work/wt-x"}), (MAIN, None))

    def test_should_match_a_worktree_in_a_bare_layout(self):
        for mode in MODES:
            fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "bare"), ("/work/wt-x", "feature/x")))
            cwd, problem = self.choose(git, gh, dirs={"/work/wt-x"}, fallback=mode)
            self.assertEqual((cwd, problem), (config.native_path("/work/wt-x"), None), mode)
            self.assertEqual(fake.count("pr view"), 1)

    def test_should_fall_back_to_the_hub_when_the_clone_is_bare(self):
        for mode in MODES:
            _fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "bare"), ("/work/wt-y", "feature/y")))
            cwd, problem = self.choose(git, gh, dirs={"/work/wt-y"}, fallback=mode)
            self.assertEqual((cwd, problem), (HUB, f"the clone at {MAIN} is bare"), mode)

    def test_should_read_the_registry_through_dot_bare_without_dot_git(self):
        _fake, gh = gh_for()
        bare = os.path.join(MAIN, ".bare")
        git = FakeGit(porcelain((bare, "bare"), ("/work/wt-x", "feature/x")))
        cwd, problem = self.choose(git, gh, dirs={"/work/wt-x"}, files={bare})
        self.assertEqual((cwd, problem), (config.native_path("/work/wt-x"), None))
        self.assertEqual(git.calls[0][:2], ["-C", bare])

    def test_should_never_match_the_main_checkout_even_on_the_pr_branch(self):
        for mode in MODES:
            _fake, gh = gh_for()
            git = FakeGit(porcelain((MAIN, "feature/x"), ("/work/wt-y", "feature/y")))
            cwd, problem = self.choose(git, gh, dirs={"/work/wt-y"}, fallback=mode)
            self.assertEqual((cwd, problem), (self.fallback_dir(mode), None), mode)

    def test_should_not_open_in_a_bare_container_when_git_fails(self):
        bare = os.path.join(MAIN, ".bare")
        for mode in MODES:
            _fake, gh = gh_for()
            git = FakeGit(rc=128, err="fatal: not a git repository")
            cwd, problem = self.choose(git, gh, files={bare}, fallback=mode)
            self.assertEqual(cwd, HUB, mode)
            self.assertIn(f"the clone at {MAIN} is bare", problem)

    def test_should_refuse_a_repo_that_is_not_owner_and_name_or_climbs_out_of_the_hub(self):
        for repo in ("..", ".", "widgets", "acme/..", "acme/.", "a/b/c", "../widgets", "", None):
            fake, gh = gh_for()
            git = FakeGit()
            self.assertEqual(self.choose(git, gh, repo=repo), (HUB, "unsafe repo name"), repo)
            self.assertEqual((git.calls, fake.calls), ([], []))

    def test_should_find_the_clone_by_the_name_part_and_ask_gh_with_the_full_name(self):
        fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
        cwd, problem = self.choose(git, gh, repo="other-owner/widgets", dirs={"/work/wt-x"})
        self.assertEqual((cwd, problem), (config.native_path("/work/wt-x"), None))
        self.assertEqual(git.calls[0][:2], ["-C", MAIN])
        self.assertEqual(fake.calls[0][0], "pr view 7 -R other-owner/widgets --json headRefName,isCrossRepository")

    def test_should_fall_back_to_the_hub_without_a_clone(self):
        fake, gh = gh_for()
        git = FakeGit()
        got = workdir.choose(HUB, REPO, 7, gh, git, isdir=lambda p: False,
                             exists=lambda p: False, os_name="posix", environ={})
        self.assertEqual(got, (HUB, None))
        self.assertEqual((git.calls, fake.calls), ([], []))

    def test_should_fall_back_to_the_hub_when_the_directory_is_not_a_clone(self):
        fake, gh = gh_for()
        git = FakeGit()
        self.assertEqual(self.choose(git, gh, files=set()), (HUB, None))
        self.assertEqual((git.calls, fake.calls), ([], []))

    def test_should_use_the_hub_for_every_miss_in_root_mode_but_still_prefer_a_worktree(self):
        _fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-y", "feature/y")))
        self.assertEqual(self.choose(git, gh, dirs={"/work/wt-y"}, fallback="root"), (HUB, None))
        _fake, gh = gh_for()
        git = FakeGit(porcelain((MAIN, "main"), ("/work/wt-x", "feature/x")))
        cwd, _problem = self.choose(git, gh, dirs={"/work/wt-x"}, fallback="root")
        self.assertEqual(cwd, config.native_path("/work/wt-x"))

    def test_should_still_gate_the_lookups_on_a_clone_in_root_mode(self):
        fake, gh = gh_for()
        git = FakeGit()
        self.assertEqual(self.choose(git, gh, files=set(), fallback="root"), (HUB, None))
        self.assertEqual((git.calls, fake.calls), ([], []))


if __name__ == "__main__":
    unittest.main()
