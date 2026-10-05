---
name: pr-review-bot
description: Watch a GitHub repo for new or updated pull requests and act as the reviewer — post CodeRabbit-style inline findings with reviews (request changes / approve); for the authed user's own PRs, post a "no changes needed" comment and merge instead of approving. Use when the user asks to "watch <repo> for PRs", "review incoming PRs on <repo>", "start the PR review bot", or "act as reviewer on <repo>".
---

# PR Review Bot

## Contents

- Needs
- Overview
- Safety rules
- Usage
- Loop setup
- Iteration procedure
  - 1. Enumerate PRs
  - 2. Decide whether this PR needs a review pass (stateless)
  - 3. Perform the actual code review
  - 4. Post the review — CodeRabbit house style
  - 5. Follow up on previously posted findings (re-review passes)
  - 6. Terminal action
  - 7. Iteration summary
- Files

## Needs

- `gh` — GitHub CLI, authenticated (check with `gh auth status`); install with
  `pacman -S github-cli`
- `jq` — builds the review JSON from files; install with `pacman -S jq`

## Overview

Continuously watch a repository and play the **reviewer** role on every open pull
request: perform a real code review of each new PR (and each new push to an
already-reviewed PR), post the findings as a GitHub review in CodeRabbit's visual
style, and drive each PR to an approval — or, for the authed user's own PRs, to a
merge.

This is the reviewer-side counterpart of `/review-watch` (which plays the PR
*author*). Do not confuse the two: this skill never fixes code on the PR branch,
never force-pushes, and never addresses review comments — it only reviews,
comments, approves, and merges.

## Safety rules

- **Never push code, force-push, or edit files on a PR branch.** Reviewer role
  only.
- **Never merge a PR authored by someone other than `$AUTHED_USER`.**
- **Never merge with failing or pending CI**, even own PRs, even with `--admin`.
- **Never approve or merge while any of your own review threads is unresolved** —
  actionable comments of any severity must be fixed or rebutted-and-resolved first.
- **Never dismiss another user's review.** Only your own stale one, and only by
  superseding it with a new review.
- **One review submission per PR per iteration** — batch all findings into it;
  no comment-spam.
- If the diff is enormous (>2k changed lines), review it in file groups within
  the same iteration but still submit a single review.
- If `gh` hits a rate limit, log it and let the next iteration retry — do not
  tight-loop.

## Usage

```
/pr-review-bot <owner/repo | github URL> [interval]
```

- `<owner/repo>` is required — e.g. `ericfisherdev/nestorage`. A full
  `https://github.com/owner/repo` URL is also accepted.
- `[interval]` defaults to `5m`.

## Loop setup

Run the watch as a recurring loop using the `/loop` skill (or `ScheduleWakeup`
in dynamic mode) at the given interval. Each iteration executes the full
**Iteration procedure** below and then goes back to sleep. Stop the loop only
when the user says so, or when the user explicitly asked to watch a single PR
and that PR is merged/closed.

At loop start (once, not per iteration):

```bash
AUTHED_USER=$(gh api user --jq .login)
```

Report to the user which repo is being watched, the interval, and the authed
login that will be treated as "own PRs".

## Iteration procedure

### 1. Enumerate PRs

```bash
gh pr list -R <owner/repo> --state open \
  --json number,title,author,isDraft,headRefOid,baseRefName,updatedAt --limit 50
```

- **Skip draft PRs.** Review them only after they are marked ready. (If the user
  asked to include drafts, review them but never merge a draft.)
- Process PRs oldest-first so long-waiting PRs are handled before fresh ones.

### 2. Decide whether this PR needs a review pass (stateless)

Do not keep local state files — derive everything from GitHub so the loop
survives restarts:

```bash
gh api repos/<owner/repo>/pulls/<n>/reviews \
  --jq '[.[] | select(.user.login=="'$AUTHED_USER'")] | last | {state, commit_id}'
```

- **No prior review by `$AUTHED_USER`** → full review needed.
- **Prior review exists and its `commit_id` == current `headRefOid`** → nothing
  new to review. Go to step 6 (merge/approve tail) — the PR may still need its
  terminal action.
- **Prior review exists but head moved** → incremental re-review: review only
  the commits since the reviewed `commit_id`
  (`gh pr diff` for full context, `gh api repos/{owner}/{repo}/compare/{reviewed_sha}...{head_sha}` for the delta),
  and also re-check whether each of your previously posted findings is now
  addressed (step 5).

### 3. Perform the actual code review

This must be a genuine review, not a lint pass. Gather context:

- `gh pr view <n> -R <owner/repo> --json title,body,files` — intent and scope.
- `gh pr diff <n> -R <owner/repo>` — the full diff.
- If the repo exists locally (e.g. under `~/dev/housedev/<repo>/main`), read the
  surrounding source there for context beyond the hunks. Otherwise fetch
  individual files at the head ref:
  `gh api repos/<owner/repo>/contents/<path>?ref=<headRefOid> --jq .content | base64 -d`.
- Honor the target repo's own CLAUDE.md / conventions when judging the code.

Review for (in priority order): correctness bugs, security issues, data-integrity
and error-handling gaps, concurrency problems, API-contract breaks, missing or
wrong tests, then maintainability. Verify every finding against the actual code
before posting it — never post a guess. Do not manufacture findings: a clean PR
gets zero comments and an approval, not filler nitpicks.

### 4. Post the review — CodeRabbit house style

Every actionable finding becomes an **inline review comment** in this exact
shape (this mirrors coderabbitai's format; a worked example follows the template):

```markdown
_<category>_ | _<severity>_ [| _⚡ Quick win_]

**<One-bold-sentence statement of the problem.>**

<1–3 sentence explanation: what happens, why it matters, what the blast radius
is. Reference concrete identifiers and the inconsistency with surrounding code
if there is one.>

<details>
<summary>🔧 Proposed fix: <short description></summary>

```diff
<minimal diff of the fix>
```

</details>

<details>
<summary>🤖 Prompt for AI Agents</summary>

```
In <path> around lines <a> - <b>, <imperative instructions an agent could
follow to apply the fix, including any tests that must be updated>.
```

</details>
```

Categories (pick the closest): `🩺 Stability & Availability`,
`🗄️ Data Integrity & Integration`, `📐 Maintainability & Code Quality`,
`🔒 Security`, `⚡ Performance`, `🧪 Test Coverage`.

Severities: `🔴 Critical`, `🟠 Major`, `🟡 Minor`, `🔵 Trivial`. Add
`| _⚡ Quick win_` when the fix is small and mechanical.

When the fix is a clean drop-in replacement for the commented lines, also add a
committable suggestion block after the proposed-fix details:

````markdown
<details>
<summary>📝 Committable suggestion</summary>

> ‼️ **IMPORTANT**
> Carefully review the code before committing. Ensure that it accurately replaces the highlighted code, contains no missing lines, and has no issues with indentation.

```suggestion
<exact replacement for the commented line range>
```

</details>
````

Worked example. Given this hunk in `internal/store/items.go`:

```diff
 func (s *Store) Save(ctx context.Context, item Item) error {
-	_, err := s.db.ExecContext(ctx, insertItem, item.ID, item.Name)
-	return err
+	s.db.ExecContext(ctx, insertItem, item.ID, item.Name)
+	return nil
 }
```

the finished inline comment (posted on lines 43-44 of the new file) is:

````markdown
_🩺 Stability & Availability_ | _🟠 Major_ | _⚡ Quick win_

**`Save` now discards the error from `ExecContext` and always returns nil.**

A failed insert (constraint violation, closed connection, cancelled context) is
reported to callers as success, so `ImportItems` will count rows that were never
written. Every other method in this file returns the `ExecContext` error.

<details>
<summary>🔧 Proposed fix: return the ExecContext error</summary>

```diff
-	s.db.ExecContext(ctx, insertItem, item.ID, item.Name)
-	return nil
+	_, err := s.db.ExecContext(ctx, insertItem, item.ID, item.Name)
+	return err
```

</details>

<details>
<summary>🤖 Prompt for AI Agents</summary>

```
In internal/store/items.go around lines 43 - 44, Save ignores the result of
s.db.ExecContext and returns nil. Capture the error from ExecContext and return
it, then update TestStore_Save to assert that a failing insert returns an error.
```

</details>
````

**Do not** copy CodeRabbit's internal HTML markers (`<!-- fingerprinting... -->`,
`<!-- cr-comment... -->`, "auto-generated by CodeRabbit" footers) — the style is
borrowed, the identity is not. Reviews post under `$AUTHED_USER`.

**Review body** (the summary at the top of the review). ALWAYS use this exact body.

```markdown
**Actionable comments posted: N**

<details>
<summary>📒 Files reviewed (M)</summary>

* `path/one.go`
* `path/two.go`

</details>
```

**Submit as one review** with all inline comments attached, via the API (not
one comment at a time):

```bash
gh api repos/<owner/repo>/pulls/<n>/reviews --input review.json
```

where `review.json` is
`{"commit_id": "<headRefOid>", "event": "<EVENT>", "body": "...", "comments": [{"path": "...", "line": <line>, "side": "RIGHT", "body": "..."}, ...]}`.
Use `start_line` + `line` for multi-line comments. Build the JSON with `jq`
from files — never hand-escape markdown into a shell string.

**Choosing the event:**

| Situation | Event |
|---|---|
| Someone else's PR, ≥1 Critical/Major finding | `REQUEST_CHANGES` |
| Someone else's PR, only Minor/Trivial findings | `COMMENT` |
| Someone else's PR, no findings | `APPROVE` (body: brief approval note) |
| **Own PR** (author == `$AUTHED_USER`), any findings | `COMMENT` — GitHub forbids approving/requesting changes on your own PR |
| **Own PR**, no findings | no review — go to step 6 |

### 5. Follow up on previously posted findings (re-review passes)

On an incremental pass, for each unresolved review thread you previously
opened, check whether the new commits address it:

- **Addressed** → reply on the thread: `` `@<author>`, confirmed — <one sentence
  on what the fix does and why it resolves the concern>. `` Then resolve the
  thread with the GraphQL below.

  ```bash
  # list unresolved threads
  gh api graphql -f query='{ repository(owner:"<OWNER>", name:"<REPO>") { pullRequest(number:<N>) { reviewThreads(first:50) { nodes { id isResolved comments(first:1) { nodes { databaseId author { login } } } } } } } }' \
    --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false) | .id'
  # resolve one
  gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:"<THREAD_ID>"}) { thread { isResolved } } }'
  ```

- **Not addressed / regressed** → reply stating what is still missing; leave
  the thread open.

When every finding is resolved and the incremental diff introduces nothing new,
dismiss your own stale `REQUEST_CHANGES` state by submitting the terminal
review from step 6 / the APPROVE row above.

### 6. Terminal action

Only reached when the current head has been fully reviewed and no unresolved
findings remain.

**Hard gate: any unresolved review thread you opened blocks this step — every
severity, 🔵 Trivial included.** An actionable comment is addressed only when
the author fixed it (verified against the new code) or rebutted it with a
reason you accept — and the thread is resolved either way (step 5). Until then:
no `APPROVE`, no "no changes needed" comment, no merge. There is no severity
threshold under which a posted finding may be ignored at merge time.

**Someone else's PR** → submit `APPROVE` (if not already approved at this
commit). Never merge another author's PR — approval is where this skill's
authority ends.

**Own PR** (author == `$AUTHED_USER`):

1. Check CI: `gh pr checks <n> -R <owner/repo>`. If checks are pending, wait
   for the next iteration; if failing, log it and leave the PR alone (fixing CI
   is the author-side `/review-watch`'s job, not this skill's).
2. Post the comment: `gh pr comment <n> -R <owner/repo> --body "No changes needed — reviewed <headRefOid short sha>, LGTM."`
3. Merge: `gh pr merge <n> -R <owner/repo> --rebase --delete-branch`. If branch
   protection blocks the merge for lack of an approving review (self-approval
   being impossible), retry with `--admin` — this is the established housedev
   merge-gate policy.
4. Log: "PR #N (own) — no findings, commented and merged."

### 7. Iteration summary

End every iteration with one log line the user can skim:

```
Checked K PRs. #12 reviewed (2 findings, changes requested) · #14 re-reviewed (all resolved, approved) · #15 own PR merged · #16 waiting on CI.
```

---

Safety rules for every step above are at the top of this file, under
[Safety rules](#safety-rules).

## Files

- [evals/test-prompts.md](evals/test-prompts.md) — three test prompts and the baseline without the skill.
