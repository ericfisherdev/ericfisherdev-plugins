---
name: setup
description: 'Choose the review command review-watcher runs for each review request, and the optional session, timing and launcher settings, and save them to the per-user review-watcher config'
argument-hint: '[--show]'
---

# Review Watcher Setup

`/review-watcher:start` opens one terminal tab per review request in the watched repositories. Each tab runs a review command of yours on its PR. This command saves which command to run, plus a few optional settings, to the per-user config so every Claude Code session on this machine picks them up. The config is `~/.claude/review-watcher/config.json`, or `$CLAUDE_CONFIG_DIR/review-watcher/config.json` when `CLAUDE_CONFIG_DIR` is set.

The repositories to watch are not set here: add them with `/review-watcher:watch owner/name`.

The helper script lives at `${CLAUDE_PLUGIN_ROOT}/scripts`. Call that directory `SCRIPTS` below, and always write its absolute path literally in commands, inside double quotes so a space in a path cannot split the argument. Never use `$` shell variables in Bash commands, because they trigger manual-approval prompts.

## Arguments

Parse `$ARGUMENTS`:

- **--show** (optional flag): print the current settings and the watched repositories, and stop. Do not ask anything.

## Step 1 - Show the current settings

```bash
python3 "{SCRIPTS}/config.py" show
python3 "{SCRIPTS}/repos.py" list
```

`config.py show` prints one JSON object with an entry per setting: `{"key", "value", "source"}`, where `source` is `config` (saved), `default` (built-in default) or `unset` (a required setting with no value). The `repos-root` entry also carries `default`, the resolved default path, and shows it as `value` while nothing is saved. If either script prints `{"error": ...}`, show the error verbatim and stop; a corrupt file is never overwritten.

Show the user a short table of every setting, its value and its source, then the watched repositories (or "none yet; add them with `/review-watcher:watch owner/name`"). Under `--show`, stop here.

## Step 2 - The review command

There is **no default**. Ask with `AskUserQuestion` (header `Review cmd`):

> Which command should review-watcher run when someone requests your review on a PR?

Options: `{value}` - **Keep the current command** (only when the setting's `source` is `config`), and Other, where the user types the full slash command, for example `/team-review {repo} {pr}`.

State what a valid command needs, in the question text or right after it:

- It is **one line and starts with `/`**.
- It contains **both `{repo}` and `{pr}`**. The watcher replaces them with the repository in `owner/name` form (`octocat/hello-world`) and the pull request number (`42`). No other `{placeholder}` is allowed.
- It uses only **letters, digits, spaces and `: _ . , = @ / # -`** besides the placeholders, and the first character after the `/` is a letter or digit. Quotes, backticks, `$`, backslashes and `; | & < > ( )` are refused.
- It runs in a **fresh session opened in the PR branch's worktree** wherever it lives; with no worktree for the branch, in the repo's clone under the repos root (`no-worktree-dir` = `clone`, the default) or in the repos root itself (`root`). It has to be a skill or command that session can find. Worktrees are found only through the clone at `{root}/{name}`, and a PR from a fork never matches one, so such a session opens in the fallback even when a worktree exists.
- It must **not switch branches in its working directory**, or it must create its own worktree: with no matching worktree the session opens in your main checkout, and a branch switch there happens under your uncommitted work.

## Step 3 - Save the command

Never put the typed text on a Bash command line: a quote, backtick or `$` in it would be parsed by the shell before the script could check it. Write the value to its own scratchpad file with the Write tool (the file holds only the command), then pass the file:

```bash
python3 "{SCRIPTS}/config.py" set review-command --value-file "{scratchpad file}"
```

The script validates the value and writes the config file in one step. If it prints `{"error": ...}`, show the message and ask again once with the same options (write the new answer to a new scratchpad file name, because the Write tool will not overwrite a file it has not read). After a second failure stop without saving. When the user kept the current command, do not call `set`.

## Step 4 - Repos root

Always ask this, right after the command is saved. Ask one `AskUserQuestion` with header `Repos root`. Use the `repos-root` entry from Step 1: its `value` is the root in use (the saved one, else the resolved default) and its `default` is the resolved default path.

> Session tabs open in the PR branch's worktree wherever it lives; otherwise in `{root}/{name}` (when `no-worktree-dir` is `clone`, the default) or in `{root}` itself (`root`). Which directory holds your repo clones?

Options:

- **Keep `{value}`**: no change, no `set`.
- **Use the default (`{default}`)**: only when `source` is `config`; runs `config.py unset repos-root`.
- **Choose another directory**: falls through to Other, where the user types an absolute path.

Save a typed path with `--value-file`, as in Step 3, with the same retry-once rule:

```bash
python3 "{SCRIPTS}/config.py" set repos-root --value-file "{scratchpad file}"
```

`/review-watcher:start`'s preflight checks that the directory exists.

## Step 5 - Optional settings

Ask **one** `AskUserQuestion` call with **three multi-select questions** (each question takes 2-4 options). Each option means "change this setting now"; anything left unselected stays as it is. Every setting left unset uses the tool default.

| Question (header) | Options |
|---|---|
| Session | `model`, `effort`, `after-report-command` |
| Timing | `interval-seconds` (default 300, at least 60), `stale-minutes` (default 45) |
| Behaviour | `launcher` (auto, windows, wsl or tmux; default auto), `no-worktree-dir` (clone or root; default clone), `close-tab-when-done` (true or false; default false) |

For every setting the user selected, ask a follow-up `AskUserQuestion` for its value, offering **Keep current (`{value}`)**, with the stored value or else the tool default, and **Clear (use the tool default)**, plus Other for a typed value. Keep current saves nothing. For `no-worktree-dir` offer the named options `clone` (open in `{root}/{name}`) and `root` (open in `{root}`) plus **Clear**. For `launcher` offer `auto` (WSL when `WSL_DISTRO_NAME` is set, Windows Terminal on Windows, tmux elsewhere), `tmux`, `windows` and `wsl`. `model` and `effort` accept only letters, digits, `.`, `_` and `-`; leaving them unset starts sessions without a `--model` or `--effort` flag. `after-report-command` is a slash command each session runs as its last action, after its report succeeds (for example one that closes its own tab). It follows the review-command character rules, but `{repo}` and `{pr}` are optional; unset adds no step. For `close-tab-when-done` offer `true` (each session closes its own tab after it reports; tmux launcher only) and `false` plus **Clear**.

Save a typed value with `--value-file`, as in Step 3; a named choice such as `clone`, `tmux` or `true` is short and plain enough to pass as `config.py set no-worktree-dir clone`. Clear a setting with:

```bash
python3 "{SCRIPTS}/config.py" unset {name}
```

## Step 6 - Confirm

Run `config.py show` and `repos.py list` again and print the table and the repositories. When no repositories are watched, tell the user to add them with `/review-watcher:watch owner/name` before `/review-watcher:start`. Remind the user that a watcher that is already running keeps the config it read at its start (the watched repositories are the exception: they are re-read every tick): stop it with Ctrl+C in its tab and run `/review-watcher:start` again to switch.
