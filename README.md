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
| [jira-tools](#jira-tools) | Jira integration tools for issues, sprints, and agile workflows | 1.4.0 |
| [confluence-tools](#confluence-tools) | Confluence integration tools for token-efficient page and folder management with caching | 1.2.1 |
| [github-tools](#github-tools) | GitHub integration tools for PR lifecycle management, review automation, and repository workflows | 1.1.0 |
| [skill-tools](#skill-tools) | Tools for auditing and maintaining Claude Code skills against Anthropic's skill-writing rules | 1.0.0 |
| [plane-tools](#plane-tools) | Work a Plane project backlog task by task through plan, implement, PR, merge, and Done | 1.0.0 |
| [pixel-art-tools](#pixel-art-tools) | Design pixel art sprites as JSON grids and render them to PNG | 1.0.0 |
| [rfp-tools](#rfp-tools) | Add park and recreation software RFPs to cross-linked requirements research | 1.0.0 |

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

### skill-tools

Tools for auditing and maintaining Claude Code skills against the 13 skill-writing rules from Anthropic's skill guide (progressive disclosure, contents lists, degrees of freedom, model fit, concise third-person writing, checklists, feedback loops, templates/examples/forks, shareability, hooks for must-hold rules, evals first, important instructions at the top, no reasoning extraction).

**Skills:**

| Skill | Description |
|-------|-------------|
| `/audit-skills` | Audit personal, project, and plugin skills rule by rule; report with file:line evidence and a numbered fix list; apply only approved fixes |

**Features:**
- Discovers skills in `~/.claude/skills`, `.claude/skills`, and installed plugin caches
- Bundled checker script decides the mechanical rules; Claude reads each skill for the judgment rules
- Report-first: nothing is edited until fix numbers are approved
- Re-audits every changed skill after fixes are applied

**Usage Examples:**

```bash
# Audit every installed skill
/audit-skills

# Audit only personal skills
/audit-skills --personal

# Audit two named skills inside installed plugins
/audit-skills --plugins --only review-watch,create-issue

# Audit a specific skill folder
/audit-skills ~/.claude/skills/my-skill

# Run the checker directly
python3 plugins/skill-tools/skills/audit-skills/scripts/audit_skills.py --all --summary
```

**Requirements:**
- Python 3.8+ (standard library only)

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

### pixel-art-tools

Claude designs pixel art as a JSON grid and renders it to PNG with a bundled script; no external API.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/pixel-art-gen` | Create, preview, and revise pixel art sprites |

**Requirements:**
- Python 3.8+ and `pip install Pillow`

---

### rfp-tools

Adds park and recreation software RFPs to a cross-linked requirements research set: extracts requirements, maps them to a shared feature catalog, and re-renders the Obsidian notes.

**Skills:**

| Skill | Description |
|-------|-------------|
| `/add-rfp` | Add one or more RFPs to the requirements research and re-render every note |

**Requirements:**
- A local RFP pipeline checkout; see the skill's `## Needs` section

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
