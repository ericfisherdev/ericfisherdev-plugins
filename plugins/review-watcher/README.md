# review-watcher

Watches the GitHub repositories you list for **review requests** (and replies on your review threads) and opens one Claude Code tab per PR, titled `Rev PR#N owner/name`, running your review command.

The watcher runs in its own tab or tmux window, titled `Review Watcher`. The review command is yours: the plugin owns the polling, the bookkeeping and the tabs, not what a review does.

## What it does

Every tick (default 5 minutes) the watcher:

1. Folds the reports that finished sessions left in the ledger and raises a `stale-session` event for sessions with no report after 45 minutes.
2. Re-reads the watched repositories from `repos.json`. With none, or with a file it cannot read, it notes that and skips the scan.
3. Scans those repositories for open PRs that request your review (`gh search prs --repo ... --review-requested <you>`, up to 20 repositories per search).
4. Opens a tab for each new item, and never a second tab for a PR that already has a session in flight.

Polling never pauses while sessions run. Each session tab is a normal interactive Claude Code session opened where the PR's code is (see Where sessions open), using that directory's permission rules; if it stops on a permission prompt, answer it in that tab.

## Prerequisites

- `gh` installed and logged in (`gh auth login`), and `python3` 3.7 or newer (standard library only)
- `claude` on the PATH
- A launcher:
  - **Linux and macOS:** `tmux`
  - **Windows:** Windows Terminal and Git for Windows (the launcher runs Git Bash)
  - **WSL:** `wt.exe` reachable from the distro

## Setup

1. `/review-watcher:setup` asks for the review command (there is no default), the repos root, then the optional settings.
2. `/review-watcher:watch owner/name [owner/name ...]` adds the repositories to watch. At least one is required.
3. `/review-watcher:start [--once] [--dry-run]` checks the setup and opens the `Review Watcher` tab. The session that ran it does no polling and can be closed.

`--dry-run` prints "would dispatch" lines and changes nothing: no session tabs (the `Review Watcher` tab still opens to show the output), no ledger writes, no log file. It does make read-only lookups (at most one `git worktree list` and one `gh pr view` per would-be dispatch) to show where each tab would open. `--once` polls once and exits.

## Watched repositories

`/review-watcher:watch` manages `repos.json` in the state directory:

| Command | Effect |
|---|---|
| `/review-watcher:watch owner/name [...]` | Add each repository. It must be `owner/name`; `gh repo view` must see it, and it is saved as GitHub spells it. One refused name saves nothing. |
| `/review-watcher:watch --remove owner/name [...]` | Stop watching each repository. |
| `/review-watcher:watch --list` | Print the list. |

The file holds `{"repos": ["owner/name", ...]}` and can also be edited by hand. The watcher re-reads it every tick, so changes apply without a restart. Repositories are matched case-insensitively. `/review-watcher:start` refuses to start with an empty list.

## Where sessions open

Each session tab opens in the first of these that exists:

1. **The PR branch's worktree.** The watcher asks git for the worktree registry of the repo's clone at `{reposRoot}/{name}` (`git worktree list`), so a worktree can live anywhere on disk. It takes the one that has the PR's head branch checked out.
2. **The repo's clone**, `{reposRoot}/{name}`, when `noWorktreeDir` is `clone` (the default).
3. **The repos root**, `{reposRoot}`, when `noWorktreeDir` is `root`, or when there is no clone.

Details:

- `{name}` is the part of `owner/name` after the slash. Two watched repositories with the same name under different owners share that clone directory.
- A clone must be a git clone (a `.git` entry, or a `.bare` directory in a bare layout). A bare clone never hosts a tab; with no matching worktree the tab opens in the repos root.
- At most one `gh pr view --json headRefName` runs per dispatch, and none when the clone has no linked worktrees or the PR already has a session in flight.
- A registered worktree whose directory is missing is skipped. So is one whose path the launcher would refuse, and one registered in the other platform's form (Windows against WSL); the last two print a note.
- A PR from a fork never matches a worktree, because a same-named local branch would be unrelated code.
- Every gh or git failure falls back to the next choice and prints a note; a lookup never stops a dispatch.

## Configuration

Stored in `~/.claude/review-watcher/config.json` (under `$CLAUDE_CONFIG_DIR` when that variable is set). Read and write it with `scripts/config.py` (`show`, `get`, `set`, `unset`); `/review-watcher:setup` does this for you. A running watcher keeps the config it read at its start.

| Key | Setting name | Default | Meaning |
|---|---|---|---|
| `reviewCommand` | `review-command` | none, required | Slash command run for a review request. One line, starts with `/`, contains `{repo}` (filled with `owner/name`) and `{pr}`. |
| `afterReportCommand` | `after-report-command` | unset (no extra step) | Slash command a session runs as its last action, only after its report succeeds, for example one that closes its own tab. Same character rules; `{repo}` and `{pr}` are optional. |
| `model` | `model` | unset (no `--model` flag) | Model for the session tabs. Letters, digits, `.`, `_`, `-`; a bracketed name such as `opus[1m]` is refused. |
| `effort` | `effort` | unset (no `--effort` flag) | Effort level for the session tabs. Same character set. |
| `intervalSeconds` | `interval-seconds` | 300 | Seconds between ticks, at least 60. Doubled for one tick after a GitHub rate limit. |
| `staleMinutes` | `stale-minutes` | 45 | Minutes without a report before a `stale-session` event. |
| `launcher` | `launcher` | auto | `auto`, `windows`, `wsl` or `tmux`. `auto` picks WSL when `WSL_DISTRO_NAME` is set, Windows on Windows or under MSYS, else tmux. |
| `reposRoot` | `repos-root` | `~/GitHub` | Directory that holds your repo clones, each at `{reposRoot}/{name}`. The watcher tab opens here. |
| `noWorktreeDir` | `no-worktree-dir` | `clone` | Where a session tab opens when no worktree has the PR branch: `clone` or `root`. |

The commands may only contain letters, digits, spaces and `: _ . , = @ / # -` besides the placeholders; quotes, backticks, `$`, backslashes and `; | & < > ( )` are refused, because the command is written into a prompt file.

## Ledger and files

Everything lives in the state directory, `~/.claude/review-watcher/` (under `$CLAUDE_CONFIG_DIR` when that variable is set):

| File | Purpose |
|---|---|
| `config.json` | The settings above |
| `repos.json` | The watched repositories |
| `ledger.json` | `seen` (review activity recorded when a session is dispatched, and while it runs), `active` and `done`, keyed `owner/name#N` |
| `ledger.json.lock` | Short writer lock; held for milliseconds, never across a scan or a tab launch |
| `poller.lock` | One watcher per machine; refreshed with a heartbeat and taken over once it is stale |
| `watcher.log` | Every event, appended |
| `prompts/` | One prompt file per session, written before its tab opens and deleted when its report is folded |
| `launchers/` | Generated bash launcher scripts; ones older than a day are swept |

## Completion contract

A session tells the watcher it is finished by running, once, the command at the end of its prompt file:

```bash
python3 "<plugin>/scripts/report.py" --ledger "<ledger.json>" --repo <owner/name> --pr <n> --session "<session>" --dispatch <id> --outcome <outcome> --head <sha>
```

| Outcome | Meaning |
|---|---|
| `posted` | Review or replies were posted to GitHub |
| `skipped` | The workflow or the developer chose not to act |
| `no-op` | There was nothing to do |
| `failed` | The workflow hit an error and could not complete |

On the next tick the watcher moves the entry to `done` and emits `finished`.

## Follow-up rules

- A new request or reply that arrives while a session is in flight is recorded and flags the entry; no second tab opens. When the session reports, newer activity than the session was dispatched for opens one follow-up review and emits `follow-up`.
- A PR is never dispatched twice at once.

## Events

Events (`dispatched`, `finished`, `follow-up`, `stale-session`) are printed in the watcher tab and appended to `watcher.log`.

## Launchers

- **tmux** (Linux and macOS): every tab is a window in the detached tmux session `review-watcher`. The first launch creates the session; later ones add windows with `-d`, so an attached client is not switched away. `tmux attach -t review-watcher` shows them. Windows keep running after their command ends (an interactive login shell takes over), so output stays readable.
- **Windows:** tabs open in a named Windows Terminal window (`review-watcher`) through a generated Git Bash launcher script with LF line endings. Git Bash is found through `CLAUDE_CODE_GIT_BASH_PATH`, then the standard Git for Windows folders, never through `bash` on the PATH, because that resolves to the WSL shim.
- **WSL:** tabs open in the same named window through `wsl.exe`, which runs a generated launcher script with `bash --login`. A login shell reads `~/.profile`, not the interactive part of `~/.bashrc`, so variables set only there may be missing in the watcher tab. Untested.

Each launcher script unsets the Claude Code session variables first, so a session does not believe it is a child of the session that started the watcher.

## Clearing a stuck PR

A session that was closed without reporting stays in flight, and the PR is skipped until it is cleared. Report it by hand:

```bash
python3 ".../scripts/report.py" --repo owner/name --pr N --outcome failed
```

`--ledger` defaults to the ledger in the state directory, and `--session` and `--head` are optional for a manual report.

## Limits

- Replies from the author are seen only while your review request is still standing; GitHub usually removes it when you submit a review.
- Commits pushed during a review are picked up only on re-request.
- Only requests for you personally are timed from the timeline. If the search returns a PR whose request went to one of your teams, its requester shows as `unknown`.
- **Second session in an open worktree:** if Claude Code or an editor is already open in the PR's worktree, the new tab shares that working tree, and the review's checkout or edits can collide with your uncommitted work.
- **Main-checkout fallback** (`noWorktreeDir` = `clone`): with no worktree for the branch, the session opens in your main checkout. A workflow that checks out a branch there switches it under your uncommitted work. Use a review command that creates its own worktree, or set `noWorktreeDir` to `root`.
- A session in a directory you have never opened Claude Code in may stop on the workspace trust prompt until you answer it in that tab; the trust is saved per directory.
- The prompt embeds the versioned plugin path of `report.py`; upgrading the plugin while a session is in flight can leave that path dangling. Clear the PR with the command above.
- The ledger starts empty, so the first tick opens a tab for every standing review request in the watched repositories with activity in the last 10 days. Run `/review-watcher:start --once --dry-run` first to see that list.

## Tests

From the repo root:

```bash
python3 -m unittest discover -s plugins/review-watcher/scripts/tests
```

All tests use a fake `gh`, an injected git runner and injected launchers; nothing touches GitHub or opens a tab.
