---
name: start
description: 'Start review-watcher: check the setup, then open the watcher in its own terminal tab or tmux window, which opens one review session per review request in the watched repositories'
argument-hint: '[--once] [--dry-run]'
---

# Review Watcher Start

This command only starts the watcher. **This session does no polling itself**: the watcher runs in its own terminal tab or tmux window titled `Review Watcher`, and it opens a further one for every review request in the watched repositories.

The helper scripts live at `${CLAUDE_PLUGIN_ROOT}/scripts`. Call that directory `SCRIPTS` below, and always write its absolute path literally in commands, inside double quotes so a space in a path cannot split the argument. Never use `$` shell variables in Bash commands, because they trigger manual-approval prompts.

## Arguments

Parse `$ARGUMENTS`:

- **--once** (optional flag): the watcher polls once, dispatches what it finds, and exits.
- **--dry-run** (optional flag): the watcher prints what it would dispatch and changes nothing: no session tabs (the `Review Watcher` tab still opens to show the output), no ledger writes, no log. It does make read-only lookups (at most one `git worktree list` and one `gh pr view` per would-be dispatch, and none when there is no clone) so each line shows the directory its tab would open in.

## Step 1 - Preflight

```bash
python3 "{SCRIPTS}/orchestrator.py" preflight
```

It prints `{"ok": true|false, "problems": [...], "notes": [...]}`. When `ok` is false, show every problem verbatim and stop. When a problem says the review command is missing, point the user to `/review-watcher:setup`. When it says no repositories are watched, point the user to `/review-watcher:watch owner/name`.

## Step 2 - Open the watcher tab

```bash
python3 "{SCRIPTS}/orchestrator.py" open-tab {flags}
```

Pass `--once` and `--dry-run` through when the user gave them. It runs the preflight again, then prints `{"ok": true, "title": "Review Watcher", "launcher": ..., "state_dir": ...}`, or `{"ok": false, "problems": [...]}` and exits 1; show the problems verbatim.

## Step 3 - Tell the user

- The watcher runs in the tab or window titled **Review Watcher**. Each session it opens is titled `Rev PR#N owner/name`.
- With the `tmux` launcher (the default on Linux and macOS) everything runs in the detached tmux session `review-watcher`: `tmux attach -t review-watcher` shows it, and new review windows open in the background (`-d`), so an attached client stays where it is.
- Each tick re-reads the watched repositories, so `/review-watcher:watch` changes apply without a restart. Other settings are read once at start.
- Session tabs open in the PR branch's worktree, else the repo's clone, else the repos root (see the plugin README, "Where sessions open").
- Events are printed in that tab and appended to `watcher.log` in the `state_dir` that `open-tab` printed.
- **Ctrl+C in the Review Watcher tab stops it.** Sessions already open keep running, and the watcher picks their reports up when it is started again.
- A PR that is stuck "in flight" because its session was closed without reporting is cleared by hand with `report.py`:

  ```bash
  python3 "{SCRIPTS}/report.py" --repo {owner/name} --pr {pr} --outcome failed
  ```

- This session did no polling and can be closed.
