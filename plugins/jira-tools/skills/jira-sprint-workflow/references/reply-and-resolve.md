# Reply-and-resolve procedure

Invoked by step 11b of the implementer procedure in SKILL.md, once per review round.

Every thread you acted on gets its own reply on that thread. One summary comment on
the PR does not discharge this, and neither does resolving a thread silently — a
resolved thread with no reply reads as "ignored" to the reviewer and leaves no record
of the reasoning.

Order matters: push first, reply second, resolve third. Replying before the push
means quoting a commit hash that does not exist yet, and fabricating a hash is worse
than saying nothing.

 i. Push the fixes for this round, then read the real hashes:
      git -C <WORKTREE> log --oneline -n <count>
    Keep the mapping you built while fixing: thread -> the commit that addressed it.
ii. Reply to each thread, one call per thread, using the databaseId of the thread's
    FIRST comment (replies attach to the thread, not to the newest comment):
      gh api --method POST \
        repos/<owner>/<repo>/pulls/<N>/comments/<comment_database_id>/replies \
        -f body="<text>"
    - Fixed: name the commit and what changed —
      "Addressed in a1b2c3d — clamp ageBoost to non-negative so future-dated items
      cannot lower the score." Do not just write "fixed" or "done".
    - Rebutted: give the reason, concretely, from the code you actually read —
      which premise is wrong, or which existing guard already covers it, with the
      file:line that shows it. Then state the follow-up: none needed, a Jira key you
      filed, or what you deferred and why. A rebuttal with no follow-up line is
      incomplete when the reviewer's underlying concern is real but out of scope.
      Example rebuttal, same shape as the fixed example above:
      "Not changed — `parseAge()` already rejects negative values at
      https://github.com/<owner>/<repo>/blob/<head-sha>/src/score/age.ts#L42, so a
      future-dated item reaches `ageBoost` as 0, never negative. Follow-up: none needed."
    - Before posting, check the thread for an existing reply of yours. Never
      double-reply on a re-review round.
iii. Resolve each thread you replied to, fixed AND rebutted alike, via GraphQL using
    the thread's node id (not the comment id):
      gh api graphql -f query='mutation {
        resolveReviewThread(input: { threadId: "<thread_node_id>" }) {
          thread { isResolved }
        }
      }'
    Resolving rebuttals is deliberate here and diverges from the address-pr-reviews
    default: step 12 cannot merge over an unresolved thread, so an unresolved
    rebuttal stalls the sprint. The reply carries the reasoning; the reviewer can
    reopen the thread if they disagree, and a reopened thread blocks the merge again.
iv. A review comment with no thread — a top-level PR comment or a review body — has
    nothing to resolve. Reply to it in place instead
    (gh pr comment <N> --body "..."), same content rules.
 v. Re-read the thread list after this pass. Zero unresolved actionable threads is
    the step 12 gate; if any remain, you missed one — go back to (ii).
