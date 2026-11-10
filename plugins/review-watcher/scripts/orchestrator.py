#!/usr/bin/env python3
"""Watch the configured GitHub repositories for review requests and open one Claude Code tab per PR.

One tick: fold the reports finished sessions left in the ledger, raise stale-session events,
re-read the watched repositories from repos.json, scan them, then dispatch a review session for
each new review request.

Nothing slow runs while the ledger lock is held: events, scans and tab launches all happen
after the `store()` block that queued them, so `report.py` never waits on them.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import launcher  # noqa: E402
import ledger  # noqa: E402
import repos  # noqa: E402
import workdir  # noqa: E402
from events import OUTCOMES, Events  # noqa: E402
from gh_client import GhClient, GhError, RateLimited, StateError  # noqa: E402
from launcher import LaunchError, LaunchTimeout, claude_argv  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
TAB_TITLE = "Review Watcher"
LOG_NAME = "watcher.log"
WAIT_CHUNK_SECONDS = 30
SCAN_TIMEOUT_SECONDS = ledger.SCAN_TIMEOUT_SECONDS


class Fatal(Exception):
    """A condition a retry cannot fix, such as an unreadable ledger."""


class ScanFailed(Exception):
    pass


def run_scan(script, args, run=subprocess.run):
    """Run one scan script and return its JSON object (the last non-empty stdout line).

    `-X utf8` makes gh output decode as UTF-8 regardless of the console code page; without it a
    PR title containing a non-ASCII character crashes the scan on Windows.
    Raises RateLimited, Fatal for an unreadable ledger, and ScanFailed for anything else.
    """
    cmd = [sys.executable, "-X", "utf8", str(SCRIPTS / script), *args]
    try:
        proc = run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=SCAN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise ScanFailed(f"{script} timed out after {SCAN_TIMEOUT_SECONDS}s")
    except OSError as err:
        raise ScanFailed(f"{script} could not be started: {err}")
    stderr = (proc.stderr or "").strip()[:500]
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    data = None
    if lines:
        try:
            data = json.loads(lines[-1])
        except ValueError:
            data = None
    if isinstance(data, dict) and data.get("error"):
        error, detail = data["error"], data.get("detail", "")
        if error == "rate_limited":
            raise RateLimited(detail or "rate limited")
        if error == "bad_state":
            raise Fatal(detail or "the ledger could not be read")
        raise ScanFailed(f"{script}: {error} {detail} {stderr}".strip())
    if proc.returncode != 0 or not isinstance(data, dict):
        raise ScanFailed(f"{script} exited {proc.returncode} without a JSON result {stderr}".strip())
    return data


def file_repos_source(path):
    """A callable that reads the watched repositories from `path` each time it is called."""
    return lambda: repos.read_repos(path)


class Context:
    def __init__(self, cfg, state_dir, me, backend, events, repos_source, scan=run_scan, clock=time.time,
                 dry_run=False, heartbeat=None, gh=None, git=workdir.run_git):
        self.cfg = cfg
        self.state_dir = Path(state_dir)
        self.me = me
        self.backend = backend
        self.events = events
        self.repos_source = repos_source
        self.scan = scan
        self.clock = clock
        self.dry_run = dry_run
        self.heartbeat = heartbeat or (lambda: None)
        self.gh = gh
        self.git = git
        self.ledger_path = str(self.state_dir / "ledger.json")
        self.prompts_dir = self.state_dir / "prompts"
        self.hub = cfg["reposRoot"]

    def store(self):
        return ledger.snapshot(self.ledger_path) if self.dry_run else ledger.update(self.ledger_path)


def key_of(repo, pr):
    return f"{repo}#{pr}"


def session_name(repo, pr):
    return f"Rev PR#{pr} {repo}"


def prompt_path(ctx, repo, pr):
    # An owner never contains `_`, so owner_name stays unambiguous.
    return ctx.prompts_dir / f"review-{repo.replace('/', '_')}-{pr}.md"


def fold(ctx, data, events, intents):
    """Move reported sessions to done and note stale ones. Runs inside a store() block."""
    now = ctx.clock()
    stale_after = ctx.cfg["staleMinutes"] * 60
    for key, entry in list(data["active"].items()):
        report = entry.get("report")
        if report:
            data["done"][key] = dict(entry)
            del data["active"][key]
            if not ctx.dry_run:
                try:
                    prompt_path(ctx, entry["repo"], entry["pr"]).unlink()
                except OSError:
                    pass
            outcome = report.get("outcome")
            head = report.get("head_sha")
            summary = f"{entry['session']}: {outcome}" + (f", head {head[:7]}" if head else "")
            events.append(("finished", dict(repo=entry["repo"], pr=entry["pr"], session=entry["session"],
                                            summary=summary)))
            if data["seen"].get(key, "") > entry.get("activity_at", ""):
                events.append(("follow-up", dict(repo=entry["repo"], pr=entry["pr"],
                                                 summary=f"new activity while {entry['session']} ran")))
                # Kept in the ledger until dispatch records the new session: the scan already
                # treats this activity as seen, so an interrupt before dispatch would lose it.
                data["done"][key]["follow_up_activity"] = data["seen"][key]
        elif now - entry["started_at"] >= stale_after and not entry.get("stale_notified_at"):
            entry["stale_notified_at"] = now
            events.append(("stale-session", dict(session=entry["session"], idle_minutes=int((now - entry["started_at"]) // 60),
                                                 repo=entry["repo"], pr=entry["pr"])))
    for key, entry in data["done"].items():
        if entry.get("follow_up_activity") and key not in data["active"]:
            intents.append(dict(repo=entry["repo"], pr=entry["pr"], url=entry.get("url", ""),
                                title=entry.get("title", ""), activity_at=entry["follow_up_activity"],
                                summary="follow-up: new activity on a reviewed PR"))


def apply_review(data, review, intents):
    active = data["active"]
    pending = set(review.get("pending_keys") or [])
    # A truncated scan is not a full snapshot: a key missing from it may still be pending.
    if not review.get("truncated"):
        # A follow-up whose launch failed is owed a retry; its request is usually gone by now.
        owed = {k for k, e in data["done"].items() if e.get("follow_up_activity")}
        for section in (data["seen"], data["done"]):
            for key in [k for k in section if k not in pending and k not in active and k not in owed]:
                del section[key]
    for item in review.get("new") or []:
        key = key_of(item["repo"], item["pr"])
        # The scan compared against an older `seen`; another poller may have dispatched it since.
        stored = data["seen"].get(key)
        if stored is not None and not item["activity_at"] > stored:
            continue
        if key in active:
            data["seen"][key] = item["activity_at"]
            active[key]["follow_up"] = True
            continue
        if item.get("trigger") == "reply":
            summary = "the author replied to your review"
        else:
            summary = f"review requested by {item.get('requester') or 'unknown'}"
        intents.append(dict(repo=item["repo"], pr=item["pr"], url=item.get("url", ""),
                            title=item.get("title", ""), activity_at=item["activity_at"], summary=summary))


def flush(ctx, events):
    for event_type, fields in events:
        ctx.events.emit(event_type, **fields)
        ctx.heartbeat()


def dispatch_all(ctx, intents):
    for intent in intents:
        dispatch(ctx, intent)
        ctx.heartbeat()


def fill_command(template, repo, pr):
    return template.replace("{repo}", repo).replace("{pr}", str(pr))


def working_dir(ctx, repo, pr):
    """Where this PR's tab opens; lookup failures fall back and are noted, never raised."""
    cwd, problem = workdir.choose(ctx.hub, repo, pr, ctx.gh, ctx.git,
                                  fallback=ctx.cfg["noWorktreeDir"],
                                  safe_cwd=getattr(ctx.backend, "safe_cwd", launcher.WIN_SAFE))
    if problem:
        ctx.events.note(f"{key_of(repo, pr)}: {problem}; opening in {cwd}")
    return cwd


def prompt_text(ctx, repo, pr, session, dispatch_id):
    command = fill_command(ctx.cfg["reviewCommand"], repo, pr)
    report = (f'python3 "{SCRIPTS.as_posix()}/report.py" --ledger "{Path(ctx.ledger_path).as_posix()}" '
              f'--repo {repo} --pr {pr} --session "{session}" --dispatch {dispatch_id} '
              f"--outcome <{'|'.join(OUTCOMES)}> --head <sha>")
    lines = [
        f"Run `{command}` now.",
        "",
        "Report exactly once, when the workflow finishes or when it cannot continue, by running:",
        "",
        f"    {report}",
        "",
        "Pick the outcome that fits:",
    ]
    lines += [f"- {name}: {meaning}" for name, meaning in OUTCOMES.items()]
    lines += ["", "Get the head sha with:", "",
              f"    gh pr view {pr} -R {repo} --json headRefOid -q .headRefOid", ""]
    after = ctx.cfg.get("afterReportCommand")
    if after:
        lines += ["Once the report command has succeeded, and only then, run "
                  f"`{fill_command(after, repo, pr)}` as your last action.", ""]
    if ctx.cfg.get("closeTabWhenDone"):
        close = (f'python3 "{SCRIPTS.as_posix()}/close_tab.py" --ledger "{Path(ctx.ledger_path).as_posix()}" '
                 f"--repo {repo} --pr {pr} --dispatch {dispatch_id}")
        lines += ["Once the report command has succeeded and every step above is done, close this tab by "
                  "running this as the very last thing you do; it ends this session:", "", f"    {close}", ""]
    return "\n".join(lines)


def dispatch(ctx, intent):
    repo, pr = intent["repo"], intent["pr"]
    key = key_of(repo, pr)
    session = session_name(repo, pr)
    summary = intent["summary"]
    if ctx.dry_run:
        cwd = working_dir(ctx, repo, pr)
        ctx.events.note(f"would dispatch {session} in {cwd} ({summary})")
        return False
    dispatch_id = uuid.uuid4().hex[:8]
    entry = {"session": session, "dispatch": dispatch_id, "repo": repo, "pr": pr, "url": intent.get("url", ""),
             "title": intent.get("title", ""), "started_at": ctx.clock(), "follow_up": False,
             "stale_notified_at": None, "activity_at": intent["activity_at"]}
    with ctx.store() as data:
        if key in data["active"]:
            return False
        data["seen"][key] = intent["activity_at"]
        follow_up = data["done"].get(key, {}).pop("follow_up_activity", None)
        data["active"][key] = entry

    def roll_back():
        with ctx.store() as data:
            data["active"].pop(key, None)
            data["seen"].pop(key, None)
            # The popped follow-up is the only record of the activity this dispatch was for.
            if follow_up is not None and key in data["done"]:
                data["done"][key]["follow_up_activity"] = follow_up

    launched = False
    try:
        cwd = working_dir(ctx, repo, pr)
        ctx.prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt = prompt_path(ctx, repo, pr)
        with open(prompt, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(prompt_text(ctx, repo, pr, session, dispatch_id))
        launched = True
        ctx.backend.open_tab(session, cwd,
                             claude_argv(session, prompt.as_posix(), ctx.cfg.get("model"), ctx.cfg.get("effort")),
                             pin_title=False)
    except LaunchTimeout as err:
        # Rolling back could open a second tab for the PR next tick. If none opened,
        # stale-session surfaces the entry and a manual report clears it.
        ctx.events.note(f"keeping {key} active: {err}")
    except (LaunchError, OSError) as err:
        roll_back()
        ctx.events.note(f"could not open a tab for {key}: {err}")
        return False
    except BaseException:
        # Once open_tab has been called the tab may already be open, so its entry must stay.
        if not launched:
            # A busy ledger must not replace the interrupt, or the watcher keeps running after Ctrl+C.
            try:
                roll_back()
            except ledger.LedgerBusy as err:
                ctx.events.note(f"could not roll back {key}: {err}")
        raise
    ctx.events.emit("dispatched", repo=repo, pr=pr, session=session, summary=summary, cwd=cwd)
    return True


def watched_repos(ctx):
    """The repositories to scan this tick, or None (with a note) when there are none or the file is bad."""
    try:
        names = ctx.repos_source()
    except repos.RepoError as err:
        ctx.events.note(f"watched repositories unreadable ({err}); skipping the scan this tick")
        return None
    if not names:
        ctx.events.note("no watched repositories; add one with /review-watcher:watch owner/name. "
                        "Skipping the scan this tick")
        return None
    return names


def status_note(ctx, review, watched):
    with ledger.snapshot(ctx.ledger_path) as data:
        in_flight = len(data["active"])
        stale = sum(1 for e in data["active"].values() if e.get("stale_notified_at"))
    new = len((review or {}).get("new") or [])
    text = (f"tick: {len(watched or [])} watched repo(s), {new} new review request(s), "
            f"{in_flight} in flight, {stale} stale")
    if (review or {}).get("truncated"):
        text += "; WARNING: a search was truncated, so some PRs were not seen"
    ctx.events.note(text)


def scan_reviews(ctx, watched):
    """The scan result, or None when it failed. Raises RateLimited."""
    args = ["--state", ctx.ledger_path, "--me", ctx.me]
    for name in watched:
        args += ["--repo", name]
    try:
        return ctx.scan("review_poll_scan.py", args)
    except ScanFailed as err:
        ctx.events.note(f"review scan failed: {err}")
        return None


def tick(ctx):
    """One poll. Returns the multiplier for the next wait (2 after a rate limit)."""
    multiplier = 1
    events, intents = [], []
    with ctx.store() as data:
        fold(ctx, data, events, intents)
    flush(ctx, events)
    dispatch_all(ctx, intents)

    ctx.heartbeat()
    review = None
    watched = watched_repos(ctx)
    if watched:
        try:
            review = scan_reviews(ctx, watched)
        except RateLimited:
            ctx.events.note("rate limited by GitHub; skipping the review scan")
            multiplier = 2
        ctx.heartbeat()

    intents = []
    if review is not None:
        with ctx.store() as data:
            apply_review(data, review, intents)
    dispatch_all(ctx, intents)
    status_note(ctx, review, watched)
    return multiplier


def preflight(cfg, which, gh, backend_factory, repos_source):
    """Everything `run` needs, checked up front. Returns {"problems", "notes", "me", "backend"}."""
    problems, notes = [], []
    me = backend = None
    if not cfg.get("reviewCommand"):
        problems.append("review-watcher is not set up: missing reviewCommand. Run /review-watcher:setup.")
    try:
        watched = repos_source()
    except repos.RepoError as err:
        problems.append(str(err))
    else:
        if watched:
            notes.append("watching: " + ", ".join(watched))
        else:
            problems.append("no repositories are watched. Add them with /review-watcher:watch owner/name.")
    if not which("gh"):
        problems.append("the GitHub CLI (gh) is not installed or not on PATH; install it from https://cli.github.com "
                        "and run 'gh auth login'")
    else:
        try:
            me = gh.current_login()
        except GhError as err:
            problems.append(f"gh is not authenticated: {err}")
    if not os.path.isdir(cfg["reposRoot"]):
        problems.append(f"the repos root is not a directory: {cfg['reposRoot']} "
                        "(set repos-root with /review-watcher:setup)")
    try:
        backend = backend_factory()
        problems += backend.problems()
    except LaunchError as err:
        problems.append(str(err))
    notes.append(f"repos root: {cfg['reposRoot']}")
    if backend is not None:
        notes.append(f"launcher: {backend.name}")
    return {"problems": problems, "notes": notes, "me": me, "backend": backend}


def poller_heartbeat(lock, token):
    """A heartbeat that raises Fatal once poller.lock is no longer ours, so a watcher that lost it stops."""
    def beat():
        if not ledger.heartbeat(lock, token):
            raise Fatal(f"{lock} is no longer held by this watcher; another watcher took over or it was removed")
    return beat


def state_dir_for(args_state_dir, env):
    return Path(args_state_dir) if args_state_dir else config.state_dir(env)


def config_env(env, state_dir):
    """An env whose CLAUDE_CONFIG_DIR makes config.py read `state_dir`; the dir must be named review-watcher."""
    if Path(state_dir).name != config.STATE_DIR_NAME:
        raise config.ConfigError(f"--state-dir must end in {config.STATE_DIR_NAME}")
    return dict(env, CLAUDE_CONFIG_DIR=str(Path(state_dir).parent))


def loop(ctx, once=False, sleep=time.sleep):
    ctx.events.start_note()
    while True:
        try:
            multiplier = tick(ctx)
        except ledger.LedgerBusy as err:
            ctx.events.note(f"{err}; trying again next tick")
            multiplier = 1
        if once:
            return 0
        remaining = ctx.cfg["intervalSeconds"] * multiplier
        while remaining > 0:
            step = min(WAIT_CHUNK_SECONDS, remaining)
            sleep(step)
            remaining -= step
            ctx.heartbeat()


def run_loop(ctx, once=False, sleep=time.sleep):
    try:
        return loop(ctx, once, sleep)
    except KeyboardInterrupt:
        with ledger.snapshot(ctx.ledger_path) as data:
            flying = [e["session"] for e in data["active"].values()]
        ctx.events.note(f"stopped; {len(flying)} session(s) still in flight" + (": " + ", ".join(flying) if flying else ""))
        return 0
    except (Fatal, StateError) as err:
        ctx.events.note(f"fatal: {err}")
        return 1


def emit_json(obj):
    print(json.dumps(obj))


def checked_setup(env, which, gh, os_name, state):
    """(cfg, preflight result) for the state dir. Raises config.ConfigError for a bad config file."""
    cfg = config.load(env)
    result = preflight(cfg, which, gh, lambda: launcher.detect(cfg["launcher"], env, os_name, state),
                       file_repos_source(state / repos.FILE_NAME))
    return cfg, result


def command_preflight(env, which, gh_factory, os_name):
    try:
        _cfg, result = checked_setup(env, which, gh_factory(), os_name, state_dir_for(None, env))
    except config.ConfigError as err:
        emit_json({"ok": False, "problems": [str(err)], "notes": []})
        return 1
    emit_json({"ok": not result["problems"], "problems": result["problems"], "notes": result["notes"]})
    return 0 if not result["problems"] else 1


def command_open_tab(args, env, which, gh_factory, os_name):
    state = state_dir_for(None, env)
    try:
        cfg, result = checked_setup(env, which, gh_factory(), os_name, state)
    except config.ConfigError as err:
        emit_json({"ok": False, "problems": [str(err)]})
        return 1
    if result["problems"]:
        emit_json({"ok": False, "problems": result["problems"]})
        return 1
    argv = ["python3", Path(__file__).resolve().as_posix(), "run", "--state-dir", Path(state).resolve().as_posix()]
    argv += [flag for flag, on in (("--once", args.once), ("--dry-run", args.dry_run)) if on]
    try:
        result["backend"].open_tab(TAB_TITLE, cfg["reposRoot"], argv)
    except LaunchError as err:
        emit_json({"ok": False, "problems": [str(err)]})
        return 1
    emit_json({"ok": True, "title": TAB_TITLE, "launcher": result["backend"].name, "state_dir": str(state)})
    return 0


def command_run(args, env, which, gh_factory, os_name, out=print, sleep=time.sleep, scan=run_scan, clock=time.time):
    try:
        state = state_dir_for(args.state_dir, env)
        gh = gh_factory()
        cfg, result = checked_setup(config_env(env, state), which, gh, os_name, state)
    except config.ConfigError as err:
        out(f"review-watcher: {err}")
        return 1
    if result["problems"]:
        for problem in result["problems"]:
            out(f"review-watcher: {problem}")
        return 1
    lock = str(state / "poller.lock")
    token = None
    if not args.dry_run:
        try:
            token = ledger.acquire_poller(lock)
        except ledger.PollerRunning as err:
            out(f"another watcher (pid {err.pid}) heartbeat {int(err.age)}s ago; stop it with Ctrl+C in its window, "
                f"or delete {lock} if it is gone")
            return 1
    try:
        events = Events(str(state / LOG_NAME), out=out, dry_run=args.dry_run)
        ctx = Context(cfg, state, result["me"], result["backend"], events,
                      file_repos_source(state / repos.FILE_NAME), scan=scan, clock=clock,
                      dry_run=args.dry_run, gh=gh,
                      heartbeat=poller_heartbeat(lock, token) if token else None)
        return run_loop(ctx, args.once, sleep)
    finally:
        if token:
            ledger.release(lock, token)


def build_parser():
    parser = argparse.ArgumentParser(description="Watch the configured GitHub repositories for review requests and "
                                                 "open one Claude Code tab per PR.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="check that everything needed to run is in place")
    for name, help_text in (("open-tab", "open the watcher in its own terminal tab or tmux window"),
                            ("run", "run the watcher in this terminal")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--once", action="store_true", help="poll once and exit")
        cmd.add_argument("--dry-run", action="store_true", help="print what would be dispatched; change nothing")
        if name == "run":
            cmd.add_argument("--state-dir", help="state directory (named review-watcher); beats CLAUDE_CONFIG_DIR")
    return parser


def main(argv=None, env=None, which=shutil.which, gh_factory=GhClient, os_name=os.name):
    args = build_parser().parse_args(argv)
    if env is None:
        workdir.clear_git_location(os.environ)
        env = os.environ
    if args.command == "preflight":
        return command_preflight(env, which, gh_factory, os_name)
    if args.command == "open-tab":
        return command_open_tab(args, env, which, gh_factory, os_name)
    return command_run(args, env, which, gh_factory, os_name)


if __name__ == "__main__":
    sys.exit(main())
