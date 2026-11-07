import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config  # noqa: E402


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.env = {}

    def tearDown(self):
        self.tmp.cleanup()

    def path(self):
        return config.config_path(self.env, self.home)

    def set(self, name, value):
        return config.set_value(name, value, self.env, self.home)

    def get(self, name):
        return config.get(name, self.env, self.home)

    def test_should_report_the_required_review_command_as_unset(self):
        self.assertEqual(self.get("review-command"), {"key": "review-command", "value": None, "source": "unset"})
        self.assertEqual(config.REQUIRED, ("review-command",))

    def test_should_report_built_in_defaults(self):
        self.assertEqual(self.get("interval-seconds")["value"], 300)
        self.assertEqual(self.get("stale-minutes")["value"], 45)
        self.assertEqual(self.get("launcher")["value"], "auto")
        self.assertIsNone(self.get("model")["value"])
        self.assertEqual(self.get("model")["source"], "default")

    def test_should_know_only_the_review_watcher_settings(self):
        self.assertEqual(set(config.SETTINGS), {
            "review-command", "after-report-command", "model", "effort", "interval-seconds", "stale-minutes",
            "launcher", "repos-root", "no-worktree-dir"})
        for removed in ("feedback-command", "sprint-filter", "slack-relay", "change-request-bot", "repos"):
            with self.assertRaisesRegex(config.ConfigError, "unknown setting", msg=removed):
                self.get(removed)

    def test_should_accept_and_reject_the_review_command(self):
        out = self.set("review-command", "  /team-review {repo} {pr} --deep  ")
        self.assertEqual(out["value"], "/team-review {repo} {pr} --deep")
        self.assertEqual(self.set("review-command", "/pr-review {repo}#{pr}")["value"], "/pr-review {repo}#{pr}")
        bad = ["review {repo} {pr}", "/x {repo}", "/x {pr}", "/x", "/x {repo} {pr} {other}",
               "/x {repo} {pr}; rm", "/x $HOME {repo} {pr}", "/x {repo} {pr}\n/y", "/x {{repo}} {pr}"]
        for value in bad:
            with self.assertRaises(config.ConfigError, msg=value):
                self.set("review-command", value)
        self.assertEqual(json.loads(self.path().read_text(encoding="utf-8"))["reviewCommand"],
                         "/pr-review {repo}#{pr}")

    def test_should_accept_an_after_report_command_without_placeholders(self):
        self.assertEqual(self.get("after-report-command"),
                         {"key": "after-report-command", "value": None, "source": "default"})
        self.assertEqual(self.set("after-report-command", "/sessions close --self --tab-close")["value"],
                         "/sessions close --self --tab-close")
        self.assertEqual(self.set("after-report-command", "/done {repo} {pr}")["value"], "/done {repo} {pr}")
        for value in ["sessions close", "/x; rm", "/x {other}", "/x $HOME"]:
            with self.assertRaisesRegex(config.ConfigError, "after-report", msg=value):
                self.set("after-report-command", value)

    def test_should_name_the_setting_in_command_errors(self):
        with self.assertRaisesRegex(config.ConfigError, "review command"):
            self.set("review-command", "nope")

    def test_should_validate_typed_settings(self):
        self.assertEqual(self.set("interval-seconds", "120")["value"], 120)
        self.assertEqual(self.set("stale-minutes", "1")["value"], 1)
        self.assertEqual(self.set("launcher", "wsl")["value"], "wsl")
        self.assertEqual(self.set("model", "opus")["value"], "opus")
        self.assertEqual(self.set("effort", "high")["value"], "high")
        self.assertEqual(self.set("repos-root", "C:/Users/x/GitHub")["value"], "C:/Users/x/GitHub")
        cases = [("interval-seconds", "59"), ("interval-seconds", "abc"), ("stale-minutes", "0"),
                 ("launcher", "mac"), ("model", "opus[1m]"), ("effort", "high now"),
                 ("repos-root", "relative/dir")]
        for name, value in cases:
            with self.assertRaises(config.ConfigError, msg=f"{name}={value}"):
                self.set(name, value)

    def test_should_accept_every_launcher_including_tmux(self):
        for choice in ("auto", "windows", "wsl", "tmux"):
            self.assertEqual(self.set("launcher", f" {choice} ")["value"], choice)
        self.assertEqual(config.LAUNCHERS, ("auto", "windows", "wsl", "tmux"))

    def test_should_read_the_value_from_a_file_and_refuse_both_sources(self):
        file = Path(self.home) / "value.txt"
        file.write_text("/team-review {repo} {pr}\n", encoding="utf-8")
        ok = argparse.Namespace(value=[], value_file=str(file))
        self.assertEqual(config.read_value(ok), "/team-review {repo} {pr}\n")
        both = argparse.Namespace(value=["/x"], value_file=str(file))
        with self.assertRaises(config.ConfigError):
            config.read_value(both)
        neither = argparse.Namespace(value=[], value_file=None)
        with self.assertRaises(config.ConfigError):
            config.read_value(neither)

    def test_should_fall_back_to_the_default_after_unset(self):
        self.set("interval-seconds", "600")
        self.set("review-command", "/x {repo} {pr}")
        self.assertEqual(config.unset("interval-seconds", self.env, self.home)["source"], "default")
        self.assertEqual(self.get("interval-seconds")["value"], 300)
        self.assertEqual(config.unset("review-command", self.env, self.home)["source"], "unset")
        self.assertEqual(json.loads(self.path().read_text(encoding="utf-8")), {})

    def test_should_keep_other_keys_when_setting(self):
        self.path().parent.mkdir(parents=True)
        self.path().write_text(json.dumps({"other": 1}), encoding="utf-8")
        self.set("model", "opus")
        self.assertEqual(json.loads(self.path().read_text(encoding="utf-8")), {"other": 1, "model": "opus"})

    def test_should_follow_claude_config_dir_into_a_review_watcher_dir(self):
        self.env = {"CLAUDE_CONFIG_DIR": str(Path(self.home) / "alt")}
        self.assertEqual(self.path(), Path(self.home) / "alt" / "review-watcher" / "config.json")
        self.env = {}
        self.assertEqual(self.path(), Path(self.home) / ".claude" / "review-watcher" / "config.json")
        self.assertEqual(config.STATE_DIR_NAME, "review-watcher")

    def test_should_never_overwrite_a_corrupt_file(self):
        self.path().parent.mkdir(parents=True)
        self.path().write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(config.ConfigError, "not valid JSON"):
            self.set("model", "opus")
        with self.assertRaises(config.ConfigError):
            config.unset("model", self.env, self.home)
        self.assertEqual(self.path().read_text(encoding="utf-8"), "{not json")

    def test_should_revalidate_hand_edited_values(self):
        self.path().parent.mkdir(parents=True)
        self.path().write_text(json.dumps({"intervalSeconds": 5}), encoding="utf-8")
        with self.assertRaisesRegex(config.ConfigError, "intervalSeconds"):
            self.get("interval-seconds")
        with self.assertRaises(config.ConfigError):
            config.load(self.env, self.home)

    def test_should_read_a_json_object_and_refuse_anything_else(self):
        path = Path(self.home) / "data.json"
        self.assertEqual(config.read_json_object(path), {})
        path.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(config.read_json_object(path), {"a": 1})
        for text, message in (("[1]", "must hold a JSON object"), ("{", "not valid JSON")):
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(config.ConfigError, message, msg=text):
                config.read_json_object(path)
        with self.assertRaisesRegex(config.ConfigError, "cannot read"):
            config.read_json_object(Path(self.home))

    def test_should_write_json_atomically_and_leave_no_temp_file(self):
        path = Path(self.home) / "nested" / "data.json"
        config.write_json_atomic(path, {"b": 2, "a": 1}, ".data-")
        self.assertEqual(path.read_text(encoding="utf-8"), '{\n  "a": 1,\n  "b": 2\n}\n')

        def always_denied(src, dst):
            raise PermissionError("WinError 5")

        with self.assertRaises(PermissionError):
            config.write_json_atomic(path, {}, ".data-", replace=always_denied, sleep=lambda s: None)
        self.assertEqual(os.listdir(path.parent), ["data.json"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1, "b": 2})

    def test_should_retry_a_permission_error_until_it_succeeds(self):
        calls = []
        sleeps = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("WinError 5")
            return "done"

        self.assertEqual(config.retry_on_permission_error(flaky, sleep=sleeps.append), "done")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(sleeps), 2)
        with self.assertRaises(PermissionError):
            config.retry_on_permission_error(lambda: (_ for _ in ()).throw(PermissionError()),
                                             attempts=3, sleep=lambda s: None)

    def test_should_resolve_the_repos_root_from_config_else_home(self):
        self.assertEqual(config.resolve_repos_root({"reposRoot": "D:/code"}, self.home, os_name="nt"), "D:\\code")
        self.assertEqual(config.resolve_repos_root({"reposRoot": "/c/Users/x/GitHub"}, self.home, os_name="nt"),
                         "C:\\Users\\x\\GitHub")
        self.assertEqual(config.resolve_repos_root({}, self.home, os_name="posix"),
                         str(Path(self.home) / "GitHub"))

    def test_should_report_the_resolved_repos_root_default(self):
        resolved = config.resolve_repos_root({}, self.home)
        self.assertEqual(self.get("repos-root"), {"key": "repos-root", "value": resolved,
                                                  "source": "default", "default": resolved})
        out = self.set("repos-root", "D:/code")
        self.assertEqual(out, {"key": "repos-root", "value": "D:/code", "source": "config",
                               "default": resolved})
        self.assertEqual(self.get("repos-root")["default"], resolved)
        self.assertNotIn("default", self.get("model"))

    def test_should_default_no_worktree_dir_to_clone(self):
        self.assertEqual(self.get("no-worktree-dir"),
                         {"key": "no-worktree-dir", "value": "clone", "source": "default"})
        self.assertEqual(config.load(self.env, self.home)["noWorktreeDir"], "clone")

    def test_should_accept_clone_and_root_for_no_worktree_dir(self):
        self.assertEqual(self.set("no-worktree-dir", " root ")["value"], "root")
        self.assertEqual(self.get("no-worktree-dir")["source"], "config")
        self.assertEqual(self.set("no-worktree-dir", "clone")["value"], "clone")

    def test_should_reject_other_no_worktree_dir_values(self):
        for value in ("hub", "", "Clone", "root now"):
            with self.assertRaises(config.ConfigError, msg=value):
                self.set("no-worktree-dir", value)
        self.assertFalse(self.path().exists())

    def test_should_convert_msys_paths_only_on_windows(self):
        self.assertEqual(config.native_path("/c/Users/x/GitHub", "nt"), "C:\\Users\\x\\GitHub")
        self.assertEqual(config.native_path("C:/Users/x", "nt"), "C:\\Users\\x")
        self.assertEqual(config.native_path("/c/Users/x", "posix"), "/c/Users/x")

    def test_should_load_every_setting_resolved(self):
        self.set("review-command", "/r {repo} {pr}")
        self.set("launcher", "tmux")
        cfg = config.load(self.env, self.home, os_name="posix")
        self.assertEqual(cfg["reviewCommand"], "/r {repo} {pr}")
        self.assertEqual(cfg["launcher"], "tmux")
        self.assertIsNone(cfg["afterReportCommand"])
        self.assertEqual(cfg["intervalSeconds"], 300)
        self.assertEqual(cfg["reposRoot"], str(Path(self.home) / "GitHub"))
        self.assertEqual(set(cfg), {key for key, *_ in config.SETTINGS.values()})


if __name__ == "__main__":
    unittest.main()
