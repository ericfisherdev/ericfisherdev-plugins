# Test prompts for pr-review-bot

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: someone else's PR with a real bug

> Start the PR review bot on acme/widgets and review incoming PRs every 5m.

Expected with skill: reports the repo, interval and authed login, then loops. For a non-draft PR by another author it reads the diff, verifies each finding against the code, and submits one review through the reviews API with CodeRabbit-style inline comments (category, severity, proposed fix, agent prompt). A Critical or Major finding gives REQUEST_CHANGES. It never pushes, merges, or edits the branch.

Baseline without skill: runs a single `gh pr list` or one-off review, posts a plain summary comment or none, has no loop, no inline comments, and may offer to fix the code itself.

## Prompt 2: own PR, no findings

> Act as reviewer on acme/widgets. My own PR #14 is ready and CI is green.

Expected with skill: finds no unresolved threads of its own, checks `gh pr checks`, posts "No changes needed — reviewed <sha>, LGTM." as a comment (not an approval), merges with `--rebase --delete-branch`, and logs "PR #14 (own) — no findings, commented and merged." If CI is pending it waits for the next iteration instead.

Baseline without skill: tries to approve its own PR (GitHub rejects it) or merges without checking CI or open threads.

## Prompt 3: re-review after new commits

> Watch acme/widgets for PRs. PR #12 got new commits after you requested changes.

Expected with skill: sees the prior review's `commit_id` differs from the current head, reviews only the new commits, replies on each addressed thread and resolves it with the `resolveReviewThread` mutation, replies on threads that are still unaddressed and leaves them open, and submits APPROVE only when no thread it opened is unresolved.

Baseline without skill: re-reviews the whole PR from scratch, leaves old threads open, and may approve while findings remain unresolved.
