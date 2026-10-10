# noto-mode

A Claude Code mod for accounts that cannot use auto mode. It approves the permission prompts auto mode would skip, and for every prompt that still reaches you it says why, and what to change so the same call passes next time.

## Install

At the prompt of a terminal session:

```
/plugin install noto-mode --marketplace ericfisherdev/ericfisherdev-plugins
```

Answer `y` to add the marketplace, pick a scope, and set the options when asked. Requires Claude Code 2.1.296 or later (function hooks).

## What it does

It hooks the engine's permission verdict (`tool.check`). Only a verdict of **ask** is touched. Everything that already decides a call stays in force:

- `permissions.deny` and `permissions.allow` rules, and the organization's managed settings.
- `permissions.ask` rules, which auto mode also honours. The prompt says which rule it was.
- A `PreToolUse` hook that asked.
- Dialogs only you can answer (plan approval, questions).

For an ask, the rules in `hooks/policy.ts` and `hooks/shell-policy.ts` decide, in auto mode's documented order:

1. **Allowed by rule.** Read-only tools; reads and edits inside the working directories (cwd, the project root, `permissions.additionalDirectories`); read-only shell commands (`ls`, `cat`, `grep`, `git status`, `git log`, `git diff`, …); project commands (`npm test`, `npm run build`, `npm ci`, `pip install -r`, `cargo test`, `go vet`, `tsc`, `prettier`, …); file operations and output redirections inside the project; read-only HTTP (`curl` GET, `WebFetch`).
2. **Never approved by the mod.** Auto mode's block list, written as patterns in `hooks/rules.ts`: privilege escalation, download-and-execute, force pushes and history rewrites, `git reset --hard` and friends, deleting critical paths (roots, home, the project itself, `.git`, system directories, wildcard deletes in temp), infrastructure and cloud changes, deploys and publishes, database drops, registry or proxy repointing, tunnels and reverse shells, flags that disarm safety guards, printing live credentials, and writes to Claude Code's own settings, hooks and plugins. These prompt you, with the reason in the dialog.
3. **Classified.** Everything else (most other shell commands, `git push`, deleting project files, new dependencies, MCP tools, scripts) goes to a small model with your recent messages, the agent's last words and the call, asked to answer `ALLOW` or `ASK` under auto mode's rules. An `ASK`, a timeout or an error leaves the prompt in place. The model's reason is shown in the dialog.

With the classifier off (`/config` › noto-mode), tier 3 simply prompts, and the dialog says so.

## What you see

- The permission dialog carries a line such as:
  `noto-mode left this to you: a force push or a remote branch deletion. To auto-approve next time: … add a permissions.allow rule in /permissions. The rule for this call would be Bash(git push:*).`
- The status line shows `noto ✓12 ?3`: approvals and prompts so far.
- A toast names each call the classifier approved (turn off with the `quiet` option).
- `/noto-mode` prints the counts, the classifier settings and the last 30 decisions with their reasons.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `classifier` | `true` | Use a model for tier 3. Off: tier 3 prompts. |
| `model` | `haiku` | Alias or model id for the classifier. |
| `timeoutMs` | `20000` | Longest classifier call before the prompt is shown instead. |
| `quiet` | `false` | No toasts on classifier approvals. |

Set them in `/config` under noto-mode, or in settings under `pluginConfigs["noto-mode"].options`.

## Caveats

- This is a rule set plus a small model, not Anthropic's auto-mode classifier. It is deliberately conservative: anything the splitter cannot read goes to the classifier, never to allow. Expect some prompts auto mode would have skipped, and read the dialog line to see what to change.
- Do not run it in a session that has real auto mode: the mod approves before the auto-mode classifier runs, so it would take over.
- A classifier approval costs one small model call. Prompt caching keeps the fixed instructions cheap.
- Counts and the `/noto-mode` log live in the module and reset when the mod reloads.

## Development

```
claude plugin validate <folder>
claude plugin test <folder>
```

The tests in `tests/` drive the rules directly and the hook through the engine.
