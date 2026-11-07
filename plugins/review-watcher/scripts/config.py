#!/usr/bin/env python3
"""Read and write the review-watcher settings in <state dir>/config.json.

The state dir is $CLAUDE_CONFIG_DIR/review-watcher when that variable is set, else
~/.claude/review-watcher. Only the keys listed in SETTINGS can be stored. The watched
repositories are not a setting: they live in repos.json and are managed by repos.py.

Usage:
  config.py show
  config.py get review-command
  config.py set review-command "/team-review {repo} {pr}"
  config.py set review-command --value-file /path/to/file   (no shell quoting involved)
  config.py unset model

Prints one JSON object. `get` and `set` print {"key", "value", "source"}, where source is
"config" when the file holds the value, "default" when the built-in default applies and
"unset" for a required setting that has no value. `repos-root` also carries "default", the
resolved fallback path, and reports it as "value" while nothing is stored. Exits 1 with
{"error": "..."} on a bad name, a bad value or an unreadable config file.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

STATE_DIR_NAME = "review-watcher"
PLACEHOLDERS = {"repo", "pr"}
COMMAND_START = re.compile(r"^/[A-Za-z0-9]")
# Quotes, backticks, `$`, backslashes, `;`, pipes and redirects are refused so the value can be
# put into a prompt file without being damaged or interpreted.
COMMAND_CHARS = re.compile(r"^[A-Za-z0-9 :_.,=@/#{}-]+$")
TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")
MSYS_DRIVE = re.compile(r"^/([A-Za-z])(?:/(.*))?$")
WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
LAUNCHERS = ("auto", "windows", "wsl", "tmux")


class ConfigError(Exception):
    pass


def state_dir(env=None, home=None):
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR")
    root = Path(base) if base else Path(home or Path.home()) / ".claude"
    return root / STATE_DIR_NAME


def config_path(env=None, home=None):
    return state_dir(env, home) / "config.json"


def retry_on_permission_error(fn, attempts=10, delay=0.05, sleep=time.sleep):
    """Run fn, retrying on PermissionError: Windows refuses os.replace while a reader holds the file."""
    for attempt in range(attempts):
        try:
            return fn()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            sleep(min(delay * (2 ** attempt), 1.0))


def native_path(value, os_name=None):
    """On Windows turn an MSYS /c/x path into C:\\x and normalise separators; elsewhere unchanged."""
    os_name = os.name if os_name is None else os_name
    if os_name != "nt":
        return value
    match = MSYS_DRIVE.match(value)
    if match:
        value = match.group(1).upper() + ":/" + (match.group(2) or "")
    return value.replace("/", "\\")


def read_json_object(path):
    """The JSON object stored at path, {} when the file is missing.

    Raises ConfigError naming the path when the file is unreadable, is not JSON or is not an object.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        raise ConfigError(f"cannot read {path}: {err}")
    try:
        data = json.loads(text)
    except ValueError as err:
        raise ConfigError(f"{path} is not valid JSON ({err}); fix or delete it")
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    return data


def write_json_atomic(path, data, prefix, replace=os.replace, sleep=time.sleep):
    """Replace the file in one step, so a crash never leaves half a file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        retry_on_permission_error(lambda: replace(tmp, str(path)), sleep=sleep)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_config(path, data):
    write_json_atomic(path, data, ".config-")


def validate_command(value, label, targets_pr=True):
    if not isinstance(value, str):
        raise ConfigError(f"the {label} must be a string")
    command = value.strip()
    if "\n" in command or "\r" in command:
        raise ConfigError(f"the {label} must be one line")
    if not COMMAND_START.match(command):
        raise ConfigError(f"the {label} must be a slash command, for example /team-review {{repo}} {{pr}}")
    if not COMMAND_CHARS.match(command):
        raise ConfigError(
            f"the {label} may only contain letters, digits, spaces and : _ . , = @ / # - and the "
            "{repo} and {pr} placeholders; quotes, $, backticks, backslashes, ; | & < > ( ) are not allowed"
        )
    unknown = set(re.findall(r"\{([^{}]*)\}", command)) - PLACEHOLDERS
    if unknown:
        raise ConfigError(f"unknown placeholder {{{sorted(unknown)[0]}}}; only {{repo}} and {{pr}} are filled in")
    if re.search(r"[{}]", re.sub(r"\{(?:repo|pr)\}", "", command)):
        raise ConfigError(f"a stray brace in the {label}; only {{repo}} and {{pr}} may use braces")
    if targets_pr and ("{repo}" not in command or "{pr}" not in command):
        raise ConfigError(f"the {label} must contain both {{repo}} and {{pr}}, so each run targets one PR")
    return command


def command_validator(label, targets_pr=True):
    return lambda value: validate_command(value, label, targets_pr)


def validate_token(value):
    if not isinstance(value, str) or not TOKEN.match(value.strip()):
        raise ConfigError("must contain only letters, digits, . _ and -")
    return value.strip()


def int_validator(minimum):
    def validate(value):
        if isinstance(value, bool):
            raise ConfigError("must be a whole number")
        if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
            value = int(value)
        if not isinstance(value, int):
            raise ConfigError("must be a whole number")
        if value < minimum:
            raise ConfigError(f"must be at least {minimum}")
        return value
    return validate


def choice_validator(*choices):
    def validate(value):
        if not isinstance(value, str) or value.strip() not in choices:
            raise ConfigError("must be one of " + ", ".join(choices))
        return value.strip()
    return validate


def validate_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("must be an absolute path")
    path = value.strip()
    if not (path.startswith("/") or WIN_DRIVE.match(path)):
        raise ConfigError("must be an absolute path")
    return path


# CLI name -> (JSON key, validator, built-in default). A default of None on a command means the
# setting is required; on any other setting it means the tool default applies.
REQUIRED = ("review-command",)
SETTINGS = {
    "review-command": ("reviewCommand", command_validator("review command"), None),
    "after-report-command": ("afterReportCommand", command_validator("after-report command", targets_pr=False), None),
    "model": ("model", validate_token, None),
    "effort": ("effort", validate_token, None),
    "interval-seconds": ("intervalSeconds", int_validator(60), 300),
    "stale-minutes": ("staleMinutes", int_validator(1), 45),
    "launcher": ("launcher", choice_validator(*LAUNCHERS), "auto"),
    "repos-root": ("reposRoot", validate_path, None),
    "no-worktree-dir": ("noWorktreeDir", choice_validator("clone", "root"), "clone"),
}


def lookup(name):
    if name not in SETTINGS:
        raise ConfigError(f"unknown setting '{name}'; known settings: {', '.join(sorted(SETTINGS))}")
    return SETTINGS[name]


def stored_value(name, data, path):
    """The validated stored value for a setting, or None when the file holds none."""
    key, validate, _default = lookup(name)
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return validate(value)
    except ConfigError as err:
        raise ConfigError(f"{path} holds an invalid {key}: {err}")


def get(name, env=None, home=None):
    _key, _validate, default = lookup(name)
    path = config_path(env, home)
    value = stored_value(name, read_json_object(path), path)
    extra = {}
    if name == "repos-root":
        extra["default"] = resolve_repos_root({}, home)
        default = extra["default"]
    if value is not None:
        return {"key": name, "value": value, "source": "config", **extra}
    if name in REQUIRED:
        return {"key": name, "value": None, "source": "unset"}
    return {"key": name, "value": default, "source": "default", **extra}


def set_value(name, value, env=None, home=None):
    key, validate, _default = lookup(name)
    try:
        clean = validate(value)
    except ConfigError as err:
        raise ConfigError(f"{name}: {err}")
    path = config_path(env, home)
    data = read_json_object(path)
    data[key] = clean
    write_config(path, data)
    return get(name, env, home)


def unset(name, env=None, home=None):
    key, _validate, _default = lookup(name)
    path = config_path(env, home)
    data = read_json_object(path)
    if key in data:
        del data[key]
        write_config(path, data)
    return get(name, env, home)


def show(env=None, home=None):
    return {name: get(name, env, home) for name in SETTINGS}


def resolve_repos_root(cfg, home=None, os_name=None):
    """Configured root, else ~/GitHub, as a native path."""
    value = cfg.get("reposRoot") or str(Path(home or Path.home()) / "GitHub")
    return native_path(value, os_name)


def load(env=None, home=None, os_name=None):
    """Every setting resolved, keyed by JSON key. The required review command is None when unset."""
    env = os.environ if env is None else env
    path = config_path(env, home)
    data = read_json_object(path)
    out = {}
    for name, (key, _validate, default) in SETTINGS.items():
        value = stored_value(name, data, path)
        out[key] = default if value is None else value
    out["reposRoot"] = resolve_repos_root(out, home, os_name)
    return out


def read_value(args):
    """The value for `set`: from --value-file when given, else the joined command-line words."""
    if args.value_file:
        if args.value:
            raise ConfigError("give the value either on the command line or with --value-file, not both")
        try:
            return Path(args.value_file).read_text(encoding="utf-8")
        except (OSError, ValueError) as err:
            raise ConfigError(f"cannot read {args.value_file}: {err}")
    if not args.value:
        raise ConfigError("no value given; pass it as arguments or with --value-file")
    return " ".join(args.value)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("show")
    getter = sub.add_parser("get")
    getter.add_argument("name")
    setter = sub.add_parser("set")
    setter.add_argument("name")
    setter.add_argument("value", nargs="*")
    setter.add_argument("--value-file", help="read the value from this file, so no shell quoting is involved")
    remover = sub.add_parser("unset")
    remover.add_argument("name")
    args = parser.parse_args()
    try:
        if args.action == "show":
            out = show()
        elif args.action == "get":
            out = get(args.name)
        elif args.action == "unset":
            out = unset(args.name)
        else:
            out = set_value(args.name, read_value(args))
    except ConfigError as err:
        print(json.dumps({"error": str(err)}))
        sys.exit(1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
