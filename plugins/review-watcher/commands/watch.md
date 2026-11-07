---
name: watch
description: 'Add, remove or list the GitHub repositories review-watcher scans for review requests, given in owner/name form'
argument-hint: 'owner/name [owner/name ...] | --remove owner/name [...] | --list'
---

# Review Watcher Repositories

The watcher scans only the repositories saved here. They are stored in `repos.json` in the state directory (`~/.claude/review-watcher/repos.json`, or `$CLAUDE_CONFIG_DIR/review-watcher/repos.json` when `CLAUDE_CONFIG_DIR` is set). A running watcher re-reads that file at the start of every tick, so a change takes effect on the next tick without a restart.

The helper script lives at `${CLAUDE_PLUGIN_ROOT}/scripts`. Call that directory `SCRIPTS` below, and always write its absolute path literally in commands, inside double quotes so a space in a path cannot split the argument. Never use `$` shell variables in Bash commands, because they trigger manual-approval prompts.

## Arguments

Parse `$ARGUMENTS`:

- **owner/name ...** (default action): add each repository. Each one must be in `owner/name` form, for example `octocat/hello-world`; a URL or a bare name is refused.
- **--remove owner/name ...**: stop watching each repository.
- **--list**, or no arguments: print the watched repositories and stop.

Before calling the script, check every name against `owner/name` with an owner of letters, digits and hyphens and a name of letters, digits, `.`, `_` and `-`. When a name does not match, show it, say the expected form, and do not run the script. Never pass any other text to the shell.

## Step 1 - Run the script

```bash
python3 "{SCRIPTS}/repos.py" add {owner/name} {owner/name}
python3 "{SCRIPTS}/repos.py" remove {owner/name}
python3 "{SCRIPTS}/repos.py" list
```

`add` checks each repository with `gh repo view` and saves it as GitHub spells it; a repository gh cannot see is refused, and then nothing from that call is saved. Matching is case-insensitive, so adding a repository already watched under another case reports it under `already`.

It prints one JSON object: `repos` (the full list after the change), `file`, and `added`/`already` for add or `removed`/`missing` for remove. On `{"error": ...}` show the message verbatim and stop.

## Step 2 - Tell the user

- List the watched repositories, and say which were added, already watched, removed, or not watched.
- When the list is now empty, say that `/review-watcher:start` refuses to start without at least one repository, and that a running watcher skips its scans until one is added.
- A session tab for a PR opens in that repository's clone at `{repos-root}/{name}` or in one of its worktrees (see `/review-watcher:setup`). Two watched repositories with the same name under different owners share that clone directory.
