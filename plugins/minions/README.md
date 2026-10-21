# minions

A Claude Code mod that turns the main conversation into a dispatcher on a small model, one that never does the work itself, and sends every task to a minion on the model tier that fits it.

## Install

At the prompt of a terminal session:

```
/plugin install minions --marketplace ericfisherdev/ericfisherdev-plugins
```

Answer `y` to add the marketplace and pick a scope. Requires Claude Code 2.1.296 or later (function hooks).

## What it does

- **The main conversation runs on Haiku.** Every request the main loop makes is rewritten to the dispatcher model (`turn.step`), whatever `/model` says. Minions keep their own models. The status line shows `minions: haiku`.
- **The dispatcher never does the work.** Its system prompt carries the routing table and the rule, and with the guard on (the default) every tool but the orchestration tools is refused to it with a message naming the minion to spawn instead. The guard is an allowlist (Agent, AskUserQuestion, SendMessage, ListAgents, TaskStop, ToolSearch, Skill, the task-list tools, plan mode), so every file, shell, code-execution, search, web and MCP tool is refused, and so is any tool a later engine release adds.
- **Six minion types are registered**, each pinned to a model and an effort:

| Minion | Model | Effort | For |
|--------|-------|--------|-----|
| `minions:scout` | Haiku | medium | Simple fetch, read and scan tasks with checkable answers |
| `minions:mapper` | Sonnet | medium | Basic, well-scoped code mapping and analysis; scans that need judgment |
| `minions:planner` | Opus | medium | Planning, dependency analysis, organization work; writes the plan a coder follows |
| `minions:coder` | Sonnet | medium | Implements a written plan, then verifies it with a check that exercises it |
| `minions:analyst` | Opus | xhigh | Intense code analysis within one sitting: root causes, tricky bugs, architecture, security review |
| `minions:researcher` | Fable | high | Deep research, whole-repository analysis, work larger than one sitting, or an analyst that fell short |

  Only the coder holds the file-writing tools. The scout has no shell at all and runs without CLAUDE.md to stay cheap. The mapper, planner, analyst and researcher keep Bash for read-only commands (git log, a test run), so for them read-only is enforced by their instructions, not by their tool list.
- **Coding work is two minions:** a planner writes the plan, then a coder implements it with the whole plan in its prompt.
- **Anything the table does not cover is the user's call:** the dispatcher asks with AskUserQuestion rather than guessing.
- **A spawn from the main conversation that is not a minion must name its `model`** (haiku, sonnet, opus or fable). One that names none is refused, so no agent ever runs on a tier nobody chose. Forks, resumes, workflow agents and spawns made inside a minion are never touched.

## Why these tiers

The table was checked against Anthropic's model guidance (the models overview, the choosing-a-model and cost pages, the Claude Code sub-agent and model-config docs, and the Haiku 5.5, Sonnet 5.5, Opus 5.5 and Fable 5.1 announcements) before it was written:

- Haiku 5.5 is Anthropic's pick for narrowly scoped subagent work with checkable outputs; scans that need judgment go to Sonnet 5.5, so the mapper exists.
- Opus 5.5 at medium effort is the recommended starting point for most agent workloads and for planning; Sonnet 5.5 is strongest at well-scoped, everyday tasks, which is what a written plan gives it. The Opus-plan, Sonnet-implement split is the pattern Claude Code ships as the `opusplan` alias.
- Opus 5.5 at higher effort matches Fable 5.1 on most analysis at a fraction of the cost, so the analyst is the first stop and the Fable researcher is the escalation: multistep research, the full context window, work larger than one sitting.

## Commands

| Command | Description |
|---------|-------------|
| `/minions` | The routing table, the dispatcher model and the guard state |

## Options

In `/config` › minions:

- `orchestratorModel` (default `haiku`): an alias (`haiku`, `sonnet`, `opus`, `fable`) or a full model id for the main conversation. An alias resolves to the current generation's id (`claude-haiku-5-5` and so on); pass a full id on Bedrock, Vertex or Foundry.
- `guard` (default on): refuse work tools to the main conversation. Off, the routing rules are advice only.

## Notes

- The dispatcher is cheap but small: give it one task at a time, and expect it to ask when a task fits no row.
- Built-in agent types (`Explore`, `Plan`, `general-purpose`) still exist; the dispatcher must pass `model` to use one.
- Development: `claude --plugin-dir plugins/minions`, `claude plugin validate plugins/minions`, `claude plugin test plugins/minions`.
