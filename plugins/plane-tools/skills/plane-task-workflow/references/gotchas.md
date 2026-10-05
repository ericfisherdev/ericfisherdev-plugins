# Plane gotchas

Plane API and glab quirks this workflow has hit. Read when a call returns something unexpected.

## Contents

- The API key is rate-limited
- This Plane build has no Epic work-item type
- `assignees` is `write_only` in the v1 serializer
- States are matched by group, not name
- Work-item keys resolve natively
- Deletes are soft
- These repos are on self-hosted GitLab, not GitHub
- glab cannot match the remote to the host on its own here, so bare `glab` fails
- `glab mr merge --auto-merge` defaults to true
- Conventional Commits
- Not every task is a code task

## Gotchas

- **The API key is rate-limited** — the stack sets `API_KEY_RATE_LIMIT=60/minute`. A
  `state` call costs roughly 4 + `--probe` requests. The helper backs off and retries on
  429, but do not sit in a polling loop against it. `--probe` defaults to 3 for this
  reason; raising it costs one request per extra task checked.
- **This Plane build has no Epic work-item type.** `issue_types` is empty and there is no
  project toggle — Epics are an EE surface. Phases are ordinary work items carrying the
  `epic` label, with tasks attached by `parent`. The helper treats *any* item with a
  parent as a workable task and any item without one as an epic. If someone creates a
  top-level task it will be read as an epic — give every task a parent.
- **`assignees` is `write_only` in the v1 serializer.** You can set it, you cannot read it
  back; a GET always shows `assignees: null`. Never test assignment by reading it.
- **States are matched by group, not name.** Plane's defaults are Backlog, Todo, In
  Progress, Done, Cancelled, mapping to groups `backlog`, `unstarted`, `started`,
  `completed`, `cancelled`. Renaming a state is safe; the helper keys off the group.
  There is **no "In Review" state by default** — a PR being open is represented by the
  task sitting in `In Progress`. If you add one, `move <KEY> "In Review"` will find it.
- **Work-item keys resolve natively**: `GET /api/v1/workspaces/<slug>/issues/READ-16/`
  returns the item. No need to search by sequence number.
- **Deletes are soft.** A deleted work item keeps its row and its `sequence_id` is not
  reused, so key numbering has gaps. That is expected, not corruption.
- **These repos are on self-hosted GitLab, not GitHub.** `gh` cannot resolve them —
  `gh repo view ericfisherdev/ereader` returns "Could not resolve to a Repository". All MR
  work goes through `glab`. One-time auth against the instance, which serves plain HTTP on
  a non-default port and SSH on 2222:
  ```sh
  glab auth login --hostname 192.168.0.16:8929 --api-protocol http --git-protocol ssh --stdin < token.txt
  ```
  The token is a GitLab personal access token with `api` scope — not the Plane key and not
  an SSH key.
- **glab cannot match the remote to the host on its own here, so bare `glab` fails**
  inside these worktrees with *"None of the git remotes configured for this repository
  point to a known GitLab host. Configured remotes: 192.168.0.16."* The remote is
  `ssh://git@192.168.0.16:2222/...`, from which glab derives the host `192.168.0.16`,
  while the authenticated host is `192.168.0.16:8929` — SSH port versus HTTP port. Setting
  `GITLAB_HOST` alone does **not** fix it (it then complains no remote corresponds to the
  variable). The combination that works, verified: `GITLAB_HOST` exported **and** an
  explicit `-R <owner>/<repo>` on every call.
  A permanent alternative, if you would rather not carry `-R`: re-auth with the git host
  and API host split apart, so the remote matches what glab expects —
  `glab auth login --hostname 192.168.0.16 --api-host 192.168.0.16:8929 --api-protocol http --git-protocol ssh --stdin`.
  Until that is done, `-R` is not optional.
- **`glab mr merge --auto-merge` defaults to true.** A bare `glab mr merge` sets
  merge-when-pipeline-succeeds and returns immediately, so the command can report success
  while nothing has merged. Always pass `--auto-merge=false`, and verify with
  `glab mr view <IID>` before moving the task to Done.
- **Conventional Commits** — lowercase subject, no trailing period. Most common failure in
  the sprint workflow; assume it here too, and expect the same of the MR title.
- **Not every task is a code task.** Phase 0's four are interviews, ADRs and program
  setup; the epic doc says outright "No production code in this phase." Those carry the
  `doc` label and route to the document-task prompt. Applying the label to future non-code
  tasks is a manual step nobody will remember — when a planner returns `kind: document`
  for an unlabelled item, add the label then.
