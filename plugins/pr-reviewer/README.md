# pr-reviewer

Reviews one GitHub pull request and posts the findings you select as a single review. It works on any repository: it reads the conventions the repository writes down (`CLAUDE.md`, `.claude/rules/`, `AGENTS.md`, `CONTRIBUTING.md`) at the PR head and has no project knowledge of its own.

```
/pr-reviewer:review owner/name 123
```

It is built to be the review command of [review-watcher](../review-watcher/README.md), and it also runs on its own.

## How a review runs

| Stage | Who | What happens |
|---|---|---|
| 1. Intake | `intake.py` | Reads the PR with `gh pr view` and `gh pr diff`, finds or creates a tree at the PR head, scopes a re-review to the new commits, and writes a review pack to disk. No model tokens. |
| 2. Review | 2 to 8 agents in parallel | Two independent reviewers always; lenses added by size and shape (below). Each reads the pack from disk and writes its findings to disk. |
| 3. Verify | `verifier` | Opens the code behind every candidate, drops what it cannot confirm, merges duplicates, removes what the PR was already told, sets severity and blocking, writes the comments. |
| 4. Refute | `refuter`, only when a finding is blocking | Tries to disprove each blocking finding. It can only lower or remove. |
| 5. Select | you | The full finding list is shown once; you choose which to post. `--auto` skips the question. |
| 6. Post | `post.py` | One review: inline comments where the diff allows, the rest in the review body. The event follows what you selected. |

The session that runs the command never reads the diff. Agents exchange files, not messages, so the orchestrating session stays small however large the PR is.

### Who reviews what

| Changed lines | Reviewers |
|---|---|
| under 200 | `defect-reviewer`, `context-reviewer` |
| 200 to 599 | + `reach-lens`; + `data-deploy-lens` when the diff has schema, migration, config, CI or dependency files |
| 600 to 1,499 | + `security-lens` |
| 1,500 or more | the same, with `defect-reviewer` run once per chunk of about 800 lines (at most 4) |

`reach-lens` also runs on a diff of any size that deletes or renames a file. It needs a tree, so it is skipped in a diff-only review.

Lines are counted after lockfiles, generated, vendored and binary files are left out, and a deleted file counts as one line: reviewers see a marker for it, and its removed content is kept in a separate file for the lens that traces what still refers to it.

| Agent | Model | Looks for |
|---|---|---|
| `defect-reviewer` | opus | Wrong behaviour, by tracing each change through its callers and callees |
| `context-reviewer` | sonnet | Written conventions, neighbouring patterns, missing halves of paired changes, comments and docs that disagree with the code, tests that cannot fail, accessibility |
| `reach-lens` | sonnet | Code outside the diff that the diff breaks or leaves stale |
| `data-deploy-lens` | sonnet | Migrations, existing data, settings and jobs the change needs and does not provide |
| `security-lens` | opus | Untrusted input, authorization and sensitive data, traced end to end |
| `verifier` | opus | Everything in stage 3 |
| `refuter` | opus | Everything in stage 4 |

All agents have `Read`, `Grep`, `Glob` and `Write` only, and write only their own result file.

## Why it is shaped this way

The design follows a benchmark of three earlier review toolkits on the same set of pull requests, graded by a blind judge:

- **Two different reviewers found more than one deeper reviewer.** Independence, not depth, raised coverage, so two reviewers with different briefs and different models always run and never see each other's output.
- **A panel of lenses found the most issues nobody else found, but only on medium and larger diffs, at about four times the cost.** So lenses are gated by size and by whether the diff has anything for them to read.
- **A verification pass that re-reads the code removed most false findings.** So every candidate is verified, not only the blocking ones.
- **The commonest error was calling a small, real finding blocking.** So blocking has one written definition, a refuter attacks every blocking finding, and the finalizer refuses to let a documentation, style, maintainability or test finding block at all.
- **Findings nobody could check were the main source of noise**: PR description versus code, guesses about monitors and production data. `rules/scope.md` rules them out.
- **Reviews went wrong when they read a newer checkout of another repository.** Agents read the pack and the tree at the PR head and nothing else.
- **Unattended runs died on early questions and on background work that outlived its wait.** The command asks one question, at the end, and every agent runs in the foreground.
- **Most of the tokens went to the orchestrating session re-reading its own context.** Scripts do the gathering and bookkeeping, and agents write to files.

## Options

| Flag | Effect |
|---|---|
| `--auto` | Post every verified finding without asking; approve when there are none |
| `--full` | Ignore earlier passes and review the whole PR again |
| `--comment-only` | Never approve or request changes |
| `--dry-run` | Run everything, show the findings and the payload, post nothing |

## The review event

| Situation | Event |
|---|---|
| A selected finding is blocking | `REQUEST_CHANGES` |
| Nothing selected is blocking | `APPROVE` |
| Your own PR, a draft, `--comment-only`, or the PR head moved after the review | `COMMENT` |
| Nothing selected | nothing is posted, unless you choose a plain approval |

Severity is `critical`, `major`, `minor` or `nit`. Blocking is a separate decision: a runtime consequence, on a reachable path, where merging is worse than not merging. See `rules/severity.md`.

## Where it runs and what it touches

- **Tree at the PR head.** If the working directory is a clone of the repository, clean and already at the PR head, it is used as it is. Otherwise the PR head is fetched (`pull/N/head`, so forks work) and a detached worktree is created under the state directory and removed at the end. No branch is ever checked out in your clone, so it is safe in a main checkout with uncommitted work.
- **No clone.** If the working directory is not a clone of the repository, the review runs from the diff alone and says so.
- **Writes.** Only under the state directory, `~/.claude/pr-reviewer/` (under `$CLAUDE_CONFIG_DIR` when set), and one review on GitHub in stage 6. Nothing is written in the repository.
- **GitHub access.** `gh pr view` and `gh pr diff` are required. `gh api` is used for existing review threads, your login and posting; if the first two are refused the review continues and says what it could not check.

| Path | Purpose |
|---|---|
| `runs/{owner}__{name}/{pr}/` | The review pack and results of the latest run: manifest, diff slices, each agent's raw findings, `verified.json`, `findings.json`, the posted payload |
| `ledger/{owner}__{name}/{pr}.json` | Every pass and the disposition of every finding: `posted`, `declined`, `dropped`, `refuted` |
| `trees/{owner}__{name}-{pr}` | The throwaway worktree, while a review is running |

## Re-reviews

The ledger makes a second review converge instead of drifting:

- No new commits since the last finished pass: nothing runs (`--full` overrides).
- New commits: only the range since the last finished pass is reviewed. Comments are still anchored against the whole PR diff.
- A finding you declined, or one the verifier or refuter removed, stays removed. It comes back only if it is critical or the code at that location changed.
- History rewritten since the last pass: the review falls back to the whole PR and says so.

## With review-watcher

```
/review-watcher:setup
```

and give `/pr-reviewer:review {repo} {pr}` as the review command (add `--auto` for unattended posting, or `--comment-only`). Each session tab then runs one review and ends with `Outcome: posted|skipped|no-op|failed`, the same four outcomes review-watcher's report command takes.

Because the review never switches a branch in its working directory, review-watcher's default `no-worktree-dir` of `clone` is safe with it.

## Requirements

- `gh` installed and logged in, `git`, `python3` 3.8 or newer (standard library only)

## Tests

From the repo root:

```bash
python3 -m unittest discover -s plugins/pr-reviewer/scripts/tests
```

The tests use fake `gh` and `git` runners and temporary directories; nothing touches GitHub or a real repository.
