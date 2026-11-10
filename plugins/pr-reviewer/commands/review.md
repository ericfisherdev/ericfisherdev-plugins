---
name: review
description: 'Review a GitHub pull request with two independent reviewers, size-gated lenses and a verification pass, then post the findings you select as one review'
argument-hint: 'owner/name PR [--auto] [--full] [--comment-only] [--dry-run]'
---

# PR Review

You are the orchestrator. Scripts gather the context and do the bookkeeping, agents review and verify, and you connect them. **Do not review the diff yourself and do not read it into this session**: the agents read the pack from disk and write their results to disk, which is what keeps this session small.

The scripts live at `${CLAUDE_PLUGIN_ROOT}/scripts`. Call that directory `SCRIPTS` below and always write its absolute path literally in commands, inside double quotes. Never use `$` shell variables in Bash commands, because they trigger manual-approval prompts. Run one command per Bash call.

## Arguments

Parse `$ARGUMENTS`:

- **owner/name** (required): the repository, for example `octocat/hello-world`.
- **PR** (required): the pull request number.
- **--auto**: post every verified finding without asking, and approve when there are none. Without it you ask once, at Step 5.
- **--full**: ignore earlier passes and review the whole PR again.
- **--comment-only**: never approve or request changes; post as a plain comment review.
- **--dry-run**: run the whole review, show the findings and the payload that would be posted, and post nothing.

If the repository or the number is missing, say what the command needs and stop. Ask the user nothing before Step 5: an early question stalls an unattended session.

## Step 1 - Intake

```bash
python3 "{SCRIPTS}/intake.py" prepare {owner/name} {pr}
```

Add `--full` when the user gave it. The script reads the PR with `gh`, finds or creates a tree at the PR head without switching any branch, scopes a re-review to the commits since the last finished pass, writes the review pack, and prints one JSON object.

- `"status": "error"`: show the error verbatim. The outcome is `failed`. Go to Step 7.
- `"status": "stop"`: show the reason. The outcome is the `outcome` it names (`no-op`). Go to Step 7.
- `"status": "ready"`: tell the user in one or two lines what will run: the mode (`full` or `incremental`), the band and line count, the agents in `stages`, and anything in `notes`.

## Step 2 - Review

Dispatch **every entry in `stages` in one message**, as parallel foreground Agent calls: `subagent_type` is the entry's `agent`, the prompt is its `prompt` copied verbatim. Do not add to the prompts, do not run the agents in the background, and do not start the verifier yet. The reviewers must not see each other's output.

Each agent replies with a count. If one fails or replies with anything else, note which; do not retry more than once. The review continues without it and Step 5 says which lens is missing.

## Step 3 - Verify

Dispatch one Agent with `verifier.agent` and `verifier.prompt` from the plan, verbatim. It checks every candidate against the code, merges duplicates, removes what the PR was already told, and writes the comments.

## Step 4 - Finalize

```bash
python3 "{SCRIPTS}/findings.py" finalize {owner/name} {pr}
```

- `"status": "refute"`: at least one finding is blocking. Dispatch one Agent with the `agent` and `prompt` it printed, verbatim, then run the same `finalize` command again.
- `"status": "error"`: the verifier's file is malformed. Send the error to a fresh verifier dispatch once (same prompt, plus the error text and "fix the file in place"), then run `finalize` again. A second error: the outcome is `failed`; go to Step 7.
- `"status": "ready"`: the first line is a JSON summary (`total`, `blocking`, `proposed_event`) and the rest is the finding list as markdown.

## Step 5 - Present and select

Print the markdown from Step 4 to the user **as it is**: every finding with its full body. It is the user's only view of the findings, so do not shorten or re-word it. Add one line naming any agent that failed in Step 2.

Then decide the selection:

- **--auto**: the selection is `all`.
- **No findings** and no `--auto`: ask with `AskUserQuestion` (header `Review`) whether to post an approval. Options: **Approve** (the selection is `none` with `--approve`), **Post nothing**.
- **Otherwise** ask with `AskUserQuestion` (header `Post`): "Which findings should I post? The review would be {proposed_event}." Options: **All {n}**, **All except nits and minors** (only when that differs from all and is not empty), **None**, and Other, where the user types numbers such as `1,3,5`. When the answer is None, ask once more whether to post a plain approval instead (**Approve** / **Post nothing**).

## Step 6 - Post

```bash
python3 "{SCRIPTS}/post.py" {owner/name} {pr} --select {all|none|1,3,5}
```

Add `--approve` for a plain approval with nothing selected (and always under `--auto`), `--comment-only` and `--dry-run` when the user gave them. The script picks the event from the selection (request changes when a selected finding is blocking, approve otherwise, comment on your own PR, on a draft, or when the head moved since the review), anchors each comment, posts one review, and records every finding as posted or declined in the ledger.

It prints `{"status", "outcome", "event", "url", "posted", "notes"}`. Tell the user the event, the number of comments, the URL and any note. Under `--dry-run`, show the payload's event and say nothing was posted. On `"status": "error"` show the error; the outcome is `failed`.

## Step 7 - Clean up and report

```bash
python3 "{SCRIPTS}/intake.py" cleanup {owner/name} {pr}
```

Run it whenever Step 1 printed `ready`, whatever happened after. It removes the throwaway worktree if one was created and nothing else.

End with one line: `Outcome: {posted|skipped|no-op|failed}`, taken from the script that decided it (`post.py`'s `outcome`, or Step 1's on a stop). If this session was started with instructions to report an outcome by running a command, as review-watcher sessions are, run that command now with this outcome and the PR head sha from the plan, exactly once.

## Rules

- Nothing is posted to GitHub except by `post.py` in Step 6, and never before the user's selection unless `--auto` was given.
- Do not edit, commit, push or check out anything in the repository.
- Do not read another checkout of this or any other repository to "check the other side"; the pack and the tree at the PR head are the whole review.
- If the user asks about a finding at Step 5, answer from the tree in the plan's `tree`; the worktree is still there until Step 7.
