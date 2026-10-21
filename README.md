# ericfisherdev-plugins

QOL plugins for Claude Code by ericfisherdev.

## Installation

Add this marketplace to Claude Code:

```bash
claude plugins:add https://github.com/ericfisherdev/claude-plugins
```

Or install individual plugins:

```bash
claude plugins:add ericfisherdev-plugins/jira-tools
```

## Available Plugins

| Plugin | Description | Version |
|--------|-------------|---------|
| [jira-tools](#jira-tools) | Jira integration tools for issues, sprints, and agile workflows | 1.4.2 |
| [confluence-tools](#confluence-tools) | Confluence integration tools for token-efficient page and folder management with caching | 1.2.1 |
| [github-tools](#github-tools) | GitHub integration tools for PR lifecycle management, review automation, and repository workflows | 1.1.1 |
| [opticlaude](#opticlaude) | Finds the repetitive tool calls that cost the most tokens, ships scripts that replace them, and audits skills against Anthropic's skill-writing rules | 1.0.2 |
| [plane-tools](#plane-tools) | Work a Plane project backlog task by task through plan, implement, PR, merge, and Done | 1.0.1 |
| [noto-mode](#noto-mode) | Approves the permission prompts auto mode would skip, for accounts without auto mode, and explains every prompt that still reaches you | 1.0.19 |
| [coding-tunes](#coding-tunes) | Plays a YouTube Music or Spotify playlist while Claude works and pauses whenever any session needs your input, in a Winamp-style pane | 1.1.0 |
| [minions](#minions) | Runs the main conversation on Haiku as a dispatcher that never does work itself and routes every task to a minion on the model tier that fits it | 0.1.0 |
| [architecture-tools](#architecture-tools) | Full architecture, behavioral, and forensic code analysis written as numbered markdown documents | 1.0.4 |

---

## Plugin Details

### jira-tools

Jira integration tools for managing issues, sprints, and agile workflows. Uses shared caching to reduce API calls and provides token-efficient output.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/jira-issue` | Fetch single issue details with preset-based truncation |
| `/create-issue` | Create Jira issues with cached metadata lookups |
| `/update-issue` | Update issues (status, assignee, labels, comments) |
| `/search-issues` | Search issues using JQL queries |
| `/link-issues` | Create relationships between issues (blocks, duplicates, etc.) |
| `/watch-issue` | Add/remove watchers on issues |
| `/log-work` | Log time entries on issues |
| `/backlog-summary` | Get summary of backlog or sprint issues |
| `/issue-analysis` | Analyze an issue and create implementation plans |
| `/analyze-backlog` | Auto-analyze top 3 unanalyzed backlog issues |
| `/sprint-info` | Get sprint details and issue list |
| `/sprint-report` | Get sprint metrics, velocity, and burndown |
| `/manage-sprint` | Create, start, or complete sprints |
| `/move-to-sprint` | Move issues between sprints or backlog |
| `/jira-board-workflow` | Run a Kanban board queue end to end: dependency audit, planning with points, implement, review, merge |
| `/jira-sprint-workflow` | Run a full Jira sprint end to end with one fresh subagent per ticket |
| `/sonar-triage` | Turn open SonarQube/SonarCloud issues into Jira tickets, or fix them directly on a PR |

**Features:**
- Token-efficient output with configurable truncation
- Preset profiles (minimal, standard, full) for common use cases
- Sprint-aware caching with different TTLs per category
- Shared cache for metadata (users, priorities, components)
- Full agile/scrum workflow support
- JQL-based search capabilities
- Human-readable names instead of IDs

**Usage Examples:**

```bash
# Fetch issue with minimal output
/jira-issue PROJ-123 --preset minimal

# Search for bugs assigned to me
/search-issues --jql "project = PROJ AND type = Bug AND assignee = currentUser()"

# Create a bug
/create-issue --project PROJ --type Bug --summary "Login fails"

# Update issue status
/update-issue PROJ-123 --status "In Progress"

# Log 2 hours of work
/log-work PROJ-123 --time 2h --comment "Fixed authentication"

# Get current sprint info
/sprint-info --board 42 --sprint active

# Move issue to current sprint
/move-to-sprint PROJ-123 --sprint 100

# Analyze an issue for implementation
/issue-analysis PROJ-123
```

**Requirements:**
- Environment variables: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`

**Cache Location:**
```
~/.jira-tools-cache.json
```

---

### confluence-tools

Confluence integration tools for managing wiki pages and folders efficiently. Uses shared caching to reduce API calls and provides token-efficient output.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/confluence-page` | Fetch single page details with preset-based truncation |
| `/list-pages` | List pages and folders in a space with type indicators (`[F]`/`[P]`) |
| `/create-page` | Create Confluence pages with storage format support |
| `/update-page` | Update pages (title, body, labels) with version management |
| `/create-folder` | Create true Confluence folders (not page containers) |
| `/search-content` | Search Confluence using CQL with parent hierarchy info |
| `/delete-page` | Delete pages or folders with auto-detection |
| `/create-blog-post` | Create blog posts with markdown support |

**Features:**
- Token-efficient output with configurable truncation
- Preset profiles (minimal, standard, full) for common use cases
- Full folder support with type indicators in tree views
- Parent hierarchy information in search results
- Shared cache for spaces, pages, and labels
- Automatic version management for updates
- CQL-based search with multiple filters

**Usage Examples:**

```bash
# Fetch page with minimal output
/confluence-page 123456 --preset minimal

# List pages and folders as tree with type indicators
/list-pages --space DEV --depth 2 --format tree

# Create a new page
/create-page --space DEV --title "API Docs" --body "<p>Content here</p>"

# Update page content
/update-page 123456 --body "<p>Updated content</p>"

# Create a true folder
/create-folder --space DEV --title "Documentation"

# Search for pages (includes parent info)
/search-content "authentication" --space DEV

# Delete a page or folder
/delete-page --id 123456

# Create a blog post
/create-blog-post --space DEV --title "Sprint Retrospective" --body-file retro.md --markdown
```

**Requirements:**
- Environment variables: `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`

**Cache Location:**
```
~/.confluence-tools-cache.json
```

---

### github-tools

GitHub integration tools for PR lifecycle management, review automation, and repository workflows.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/review-watch` | Monitor PRs and automatically manage their lifecycle — fix CI, respond to reviews, rebase, and merge |
| `/github-board-workflow` | Run a GitHub Projects queue end to end: dependency audit, planning with points, implement, review, merge |
| `/pr-review-bot` | Watch a repo for new or updated PRs and act as the reviewer with inline findings |

**Features:**
- Automated PR lifecycle management (draft → review → merge)
- CI failure diagnosis and auto-fix for draft PRs
- Automatic rebase when base branch is merged into main
- Review comment response with apply/decline actions
- CodeRabbit rate limit handling
- Multi-PR and single-PR watch modes
- Worktree-based isolation for concurrent PR processing

**Usage Examples:**

```bash
# Watch all your open PRs
/review-watch

# Watch a specific PR
/review-watch 42
/review-watch https://github.com/owner/repo/pull/42
```

**Requirements:**
- GitHub CLI (`gh`) authenticated with repo access

---

### opticlaude

Token hygiene for Claude Code. Measures which repetitive tool calls in your session transcripts cost the most, ships scripts that replace the common ones, enforces them with deny rules, and audits skills against the 13 skill-writing rules from Anthropic's skill guide.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/scriptify` | Scan session history for a period (`--period 1w`, `2d`, `12h`; default `2w`), rank repetitive task shapes by estimated token savings, propose scripts and conflict-checked deny rules |
| `/opticlaude:setup` | Copy the helper scripts to `~/.claude/scripts/opticlaude/`, add the deny rules to `~/.claude/settings.json`, write a pointer block into the global CLAUDE.md (`--strict`, `--uninstall`, `--dry-run`) |
| `/audit-skills` | Audit personal, project, and plugin skills rule by rule; report with file:line evidence and a numbered fix list; apply only approved fixes |

**Helper scripts** (`plugins/opticlaude/scripts/`, installed by `/opticlaude:setup`, all `--help`):

| Script | Replaces | What it does |
|--------|----------|--------------|
| `patch.py` | inline `python3 - <<EOF ... s.replace()` edit heredocs | Anchored string-replace edits from a compact hunk spec; all-or-nothing, CRLF-safe, one-line failure with nearest-line hint |
| `dts_lookup.py` | `sed -n A,Bp` and `grep` over `.d.ts` files | Exact declaration blocks (with JSDoc, real line numbers) by name or `-g REGEX` |
| `src_outline.py` | `for f in ...; cat -n` loops, orientation reads | Symbols with line numbers for TS/JS/Python/Go/Rust/PHP/JVM; `--dump` strips blank lines |
| `pr.py` | `gh pr view --json`, `gh run list`, review-thread GraphQL, `gh api .../pulls/N/comments` | One line per PR (state, review, merge state, CI counts, unresolved threads); `checks`, `threads`, `resolve`, `reply` |

**Deny rules written by setup:** `Bash(sed -n *.d.ts*)`, `Bash(for f in *cat -n*)`, `Bash(gh run list *)`. `--strict` adds `Bash(gh pr view *)`, `Bash(gh api graphql *)` and `Bash(gh api repos/*/pulls/*)`, which break skills that call those directly (github-board-workflow, pr-review-bot, review-watch, code-review). Setup records the rules it added in `~/.claude/scripts/opticlaude/installed-rules.json`; `--uninstall` removes only those. Settings and CLAUDE.md are written through a temp file and rename.

**Usage Examples:**

```bash
# Rank scriptable task shapes from the last week
/scriptify --period 1w

# Only one project, last two days
/scriptify --period 2d --project obsidiboard

# Install scripts, deny rules and CLAUDE.md pointers
/opticlaude:setup

# Audit every installed skill
/audit-skills

# Run the analyzers directly
python3 plugins/opticlaude/skills/scriptify/scripts/scriptify.py --period 2w --format json
python3 plugins/opticlaude/skills/audit-skills/scripts/audit_skills.py --all --summary
```

**Requirements:**
- Python 3.10+ (standard library only)
- GitHub CLI (`gh`) authenticated, for `pr.py`

---

### plane-tools

Works a Plane project's backlog one task at a time, each carried from plan to merge to Done before the next begins, with every task delegated to a fresh subagent.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/plane-task-workflow` | Work the Plane backlog (up to 10 tasks per run): plan, implement, PR, merge, Done |

**Requirements:**
- `glab` (repos are on GitLab), Python 3.8+; see the skill's `## Needs` section

---

### noto-mode

A mod (function-hooks plugin) for accounts that cannot use auto mode. It hooks the engine's permission verdict and turns only would-be prompts into approvals, following auto mode's documented order: read-only actions and edits inside the project are allowed by rule; auto mode's block list (sudo, download-and-execute, force pushes, history rewrites, deleting critical paths, infra and cloud changes, deploys, registry repointing, tunnels, safety-disarming flags, credential printing) is never approved by the mod; everything else is judged by a small model with your recent messages. Every prompt that still reaches you carries a line saying why, and what to change so the same call passes next time (the exact `permissions.allow` rule, `/add-dir`, or the classifier switch).

**Commands:**

| Command | Description |
|---------|-------------|
| `/noto-mode` | Counts, classifier settings and the last 30 decisions with their reasons |

**Features:**
- Deny, allow and ask rules, managed settings and PreToolUse hooks all keep their say
- Status line entry (`noto ✓12 ?3`) and a toast per classifier approval
- Options in `/config` › noto-mode: `classifier` on/off, `model` (default `haiku`), `timeoutMs`, `quiet`
- Conservative by design: anything the shell splitter cannot read goes to the classifier, never to allow

**Install:**

```bash
/plugin install noto-mode --marketplace ericfisherdev/ericfisherdev-plugins
```

**Requirements:**
- Claude Code 2.1.296 or later (function hooks)
- Not for sessions that already run auto mode: the mod approves before the auto-mode classifier runs

---

### coding-tunes

A mod (function-hooks plugin) that plays a YouTube Music or Spotify playlist once Claude has been working for 10 seconds, and pauses the moment a permission prompt or a question needs you. Every Claude session on the machine shares one player: while any session waits on your input, no other session can resume it. A Winamp-style pane shows the player, track, playlist, elapsed time and spectrum, with previous, play, pause and next controls.

**Commands:**

| Command | Description |
|---------|-------------|
| `/coding-tunes --player=ytmusic --list=<playlist id>` | Load a playlist (ids or links); it plays once Claude works 10 seconds |
| `/coding-tunes` | Ask for the player and the playlist |
| `/coding-tunes --setup` | Save the default player and playlist; link Spotify or pick a browser login for private YouTube playlists |
| `/coding-tunes --play` / `--pause` / `--next` / `--prev` | Transport controls that run at once, even mid-turn |
| `/coding-tunes --stop` | Stop the shared player and close the pane |

**Features:**
- Pauses on permission dialogs and AskUserQuestion; resumes when they are answered
- One shared player across sessions; a session awaiting input holds it paused for all
- Private YouTube Music playlists through a browser's signed-in cookies (Zen, Firefox, Chrome, Brave, ...)
- Pane hotkeys `z` `x` `c` `b` (previous, play, pause, next), as in Winamp

**Install:**

```bash
/plugin install coding-tunes --marketplace ericfisherdev/ericfisherdev-plugins
```

**Requirements:**
- Claude Code 2.1.296 or later (function hooks), Linux, Python 3
- YouTube Music: `mpv` and `yt-dlp`
- Spotify: Premium, a Spotify developer app's client id, and an open Spotify client

---

### minions

A mod (function-hooks plugin) that turns the main conversation into a dispatcher on Haiku, one that never does the work itself. Every request of the main loop runs on the dispatcher model whatever `/model` says; the file, shell, search, web and MCP tools are refused to it with a message naming the minion to spawn instead; and six minion types are registered, each pinned to a model tier: `minions:scout` (Haiku) for simple reads and scans, `minions:mapper` (Sonnet) for basic code mapping, `minions:planner` (Opus) for plans and dependency analysis, `minions:coder` (Sonnet) to implement a written plan, `minions:analyst` (Opus at xhigh) for intense code analysis, `minions:researcher` (Fable) for deep research and work larger than one sitting. Coding work is always a planner then a coder. Work the table does not cover is put to you with a question. Any other agent spawned from the main conversation must name its model.

**Commands:**

| Command | Description |
|---------|-------------|
| `/minions` | The routing table, the dispatcher model and the guard state |

**Features:**
- Status line entry (`minions: haiku`)
- Options in `/config` › minions: `orchestratorModel` (default `haiku`), `guard` on/off
- Routing table checked against Anthropic's model guidance before it was written (see the plugin README)

**Install:**

```bash
/plugin install minions --marketplace ericfisherdev/ericfisherdev-plugins
```

**Requirements:**
- Claude Code 2.1.296 or later (function hooks)

---

### architecture-tools

Runs a 33-section analysis of a repository (or one mono-repo subdirectory) and writes each section as its own numbered markdown file, plus an index. Covers architecture (API, database, auth, dependencies, events, deployment, security), behavioral git analysis (hotspots, change coupling, bus factor, churn), and forensic analysis (code age, defect prediction, Conway's Law, code city).

**Skills:**

| Skill | Description |
|-------|-------------|
| `/full-analysis` | Run all 33 analyses in order into `.analysis/full/` (or `.analysis/full/<subdirectory>/`) with an index |

**Usage Examples:**

```bash
# Whole repository
/full-analysis

# One subdirectory of a mono-repo
/full-analysis apps/frontend
```

**Requirements:**
- `git` with history; authenticated `gh` CLI for the PR complexity section only (skipped without it)

---

## Contributing

To add a new plugin:

1. Create a directory under `plugins/{plugin-name}/`
2. Add a `plugin.json` manifest in `plugins/{plugin-name}/.claude-plugin/`
3. Add commands, agents, skills, or hooks as needed
4. Register the plugin in `.claude-plugin/marketplace.json`
5. Document the plugin in this README

## License

MIT
