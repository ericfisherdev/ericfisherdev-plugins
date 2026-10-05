# Background

Why the workflow is built the way it is, and an alternative way to run it. None of this is needed to run the sprint; read it when changing the design.

## Contents

- Why it is built this way
- Maximum-freshness variant

## Why it is built this way

The source workflow says "clear your context after each merge." A session cannot clear
itself — `/clear` is user-invoked only, and no hook can trigger it. Subagents solve the
same problem natively: each starts with a fresh context and returns only a short summary.

It also said "SWITCH THE MODEL TO FABLE / SONNET". You do not switch anything — spawn
each subagent with a `model` override instead:

| Phase | Model | Why |
|---|---|---|
| Planning | `fable` | Research + plan writing, one agent per ticket, run in parallel |
| Implementation | `sonnet` | Code, CI, merge — one agent per ticket, strictly sequential |
| Security triage (Sonar repos) | `opus` | Judging real risk vs. false positive on Sonar hotspots |
| Orchestration | inherit | You stay on whatever the session is; you only route and report |

## Maximum-freshness variant

Subagents give a fresh context but share the session's process. For a genuinely new
process per ticket — the closest thing to "clear context between tasks" — drive the
implementation phase headlessly, using **Jira as the state store** so each invocation
rediscovers where it is (`<SKILL_DIR>` is this skill's folder):

```sh
while :; do
  KEY=$(python "<SKILL_DIR>/scripts/sprint_state.py" NSTR --json \
        | python -c 'import json,sys; print(json.load(sys.stdin)["next_ticket"] or "")')
  [ -z "$KEY" ] && break
  claude -p "Use the jira-sprint-workflow skill's implementer procedure for $KEY only."
done
```

Each `claude -p` is a brand-new session. Slower and harder to supervise, but nothing
carries over between tickets at all.
