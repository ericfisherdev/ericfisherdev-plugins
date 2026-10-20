---
name: setup
description: Installs the opticlaude helper scripts (patch.py, dts_lookup.py, src_outline.py, pr.py) to a stable path, adds the matching deny rules to the user's Claude Code settings, and writes a pointer section into the global CLAUDE.md. Use when the user runs "/opticlaude:setup", asks to "install the opticlaude scripts", "set up opticlaude", "add the opticlaude deny rules", or after updating the plugin.
---

# Opticlaude setup

Copy the scripts, add the deny rules, point CLAUDE.md at them. Dry run first.

## Contents

- Needs
- Usage
- Workflow
- What gets written
- Reference files

## Needs

- Python 3.10 or newer, standard library only.
- `scripts/setup.py`, bundled in this skill folder.
- Write access to `~/.claude/settings.json`, `~/.claude/CLAUDE.md` and `~/.claude/scripts/` (or the same under `$CLAUDE_CONFIG_DIR`).
- `pr.py` additionally needs the GitHub CLI (`gh`) authenticated.

## Usage

```
/opticlaude:setup              # install
/opticlaude:setup --strict     # also deny `gh pr view` and `gh api graphql`
/opticlaude:setup --uninstall  # remove scripts, deny rules and the CLAUDE.md section
```

## Workflow

1. Run the dry run and show the user its output:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/setup.py --dry-run
   ```

2. Run it for real with the same flags the user asked for. Pass `--strict` only when the user asked for it; say first that the two strict rules break skills that call `gh pr view` or `gh api graphql` directly (github-board-workflow, pr-review-bot, review-watch, code-review).

3. Report what changed: scripts directory, deny rules added, CLAUDE.md section written. Remind the user to re-run after a plugin update so the copies pick up new script versions.

## What gets written

- `~/.claude/scripts/opticlaude/*.py`: copies of the plugin's `scripts/` directory, executable.
- `permissions.deny` in `~/.claude/settings.json`: `Bash(sed -n *.d.ts*)`, `Bash(grep *.d.ts*)`, `Bash(for f in *cat -n*)`, `Bash(gh run list *)`, `Bash(gh api repos/*/pulls/*)`. Existing entries are kept.
- `~/.claude/CLAUDE.md`: a block between `<!-- opticlaude:begin -->` and `<!-- opticlaude:end -->` naming each script and the command it replaces. Re-running replaces the block in place.

## Reference files

- [evals/test-prompts.md](evals/test-prompts.md): three test prompts and the baseline behaviour without this skill; read when changing the workflow.
- `scripts/setup.py`: the installer; `--help` lists the paths and flags.
