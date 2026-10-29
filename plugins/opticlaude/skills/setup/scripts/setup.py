#!/usr/bin/env python3
"""Install the opticlaude helper scripts, deny rules and CLAUDE.md pointers.

    setup.py                 install: copy scripts, add deny rules, write the CLAUDE.md section
    setup.py --dry-run       show what would change
    setup.py --strict        also deny `gh pr view`, `gh api graphql` and `gh api repos/*/pulls/*`
                             (breaks skills that call them directly, e.g. review-watch, pr-review-bot)
    setup.py --uninstall     remove the scripts directory, the deny rules setup added and the CLAUDE.md section

Paths (override with flags):
  scripts     ~/.claude/scripts/opticlaude/      stable copy, so the pointers survive plugin version bumps
  settings    ~/.claude/settings.json            permissions.deny gains the rules below
  CLAUDE.md   ~/.claude/CLAUDE.md                a block between <!-- opticlaude:begin --> and <!-- opticlaude:end -->

The rules setup adds are recorded in <scripts>/installed-rules.json so that --uninstall
removes only those and leaves rules the user wrote by hand. Files are written through a
temp file and rename, so a crash never leaves settings.json or CLAUDE.md truncated.

Re-run after updating the plugin so the copies pick up the new script versions.
Honors $CLAUDE_CONFIG_DIR for every default path.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import tempfile

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SOURCE_SCRIPTS = os.path.join(PLUGIN_ROOT, "scripts")
BEGIN, END = "<!-- opticlaude:begin -->", "<!-- opticlaude:end -->"
LEGACY_HEADER = "# Helper Scripts (`~/.claude/scripts/`, run `--help` for usage)"
MANIFEST = "installed-rules.json"

DENY_RULES = [
    "Bash(sed -n *.d.ts*)",
    "Bash(for f in *cat -n*)",
    "Bash(gh run list *)",
]
# Rules that break marketplace skills which call these commands directly
# (github-tools review-watch and pr-review-bot read and submit reviews through
# `gh api repos/.../pulls/...`; pr.py has no replacement for that).
STRICT_RULES = [
    "Bash(gh pr view *)",
    "Bash(gh api graphql *)",
    "Bash(gh api repos/*/pulls/*)",
]
# Rules earlier versions wrote that deny legitimate commands. `*` matches any text,
# so `Bash(grep *.d.ts*)` also denied `grep ... --exclude=*.d.ts`; no glob can tell a
# `.d.ts` operand from that flag, so the grep case is left to the CLAUDE.md pointer.
# Install and uninstall both drop these.
LEGACY_RULES = [
    "Bash(grep *.d.ts*)",
]


def config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def claude_md_section(scripts_dir: str) -> str:
    d = scripts_dir.replace(os.path.expanduser("~"), "~", 1)
    return "\n".join([
        BEGIN,
        "# Helper Scripts (opticlaude)",
        f"Scripts live in `{d}/`; run any with `--help`. Installed by /opticlaude:setup.",
        f"- File edits from Bash: `{d}/patch.py` reads hunks on stdin (`@@ path` / old / `===` / new; `@@*` replaces all). Never write inline `python3 - <<EOF ... s.replace(...)` edit scripts.",
        f"- Type declarations in `.d.ts` files: `{d}/dts_lookup.py FILE Name...` or `-g REGEX`. Never `sed -n A,Bp` or `grep` a `.d.ts` file.",
        f"- Orientation in a codebase: `{d}/src_outline.py PATH...` (symbols + line numbers), `--dump [-l A-B]` for blank-stripped content. Never `for f in ...; cat -n` loops.",
        f"- Pull requests, workflow runs and releases: `{d}/pr.py status|checks|threads|resolve|reply|runs|release [-R owner/repo]`. `runs [-w WORKFLOW] [-b BRANCH_OR_TAG]` covers runs no PR owns, such as a tag push; `release TAG` finds drafts too. Prefer it over `gh pr view --json`, `gh run list`, `gh release view`, `gh api graphql` review-thread queries and `gh api repos/*/pulls/N/comments`.",
        END,
        "",
    ])


def replace_section(text: str, section: str | None) -> str:
    """Return text with the marked block replaced (or removed when section is None)."""
    text = re.sub(re.escape(BEGIN) + r"[\s\S]*?" + re.escape(END) + r"\n?", "", text)
    text = remove_legacy(text)
    text = text.rstrip("\n") + "\n" if text.strip() else ""
    if section is None:
        return text
    return text + ("\n" if text else "") + section


def remove_legacy(text: str) -> str:
    """Drop the unmarked section an earlier manual install wrote (header through the next heading)."""
    start = text.find(LEGACY_HEADER)
    if start < 0:
        return text
    rest = text[start + len(LEGACY_HEADER):]
    next_heading = re.search(r"^# ", rest, re.M)
    end = start + len(LEGACY_HEADER) + (next_heading.start() if next_heading else len(rest))
    return text[:start].rstrip("\n") + "\n" + text[end:]


def load_settings(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_atomic(path: str, text: str) -> None:
    """Write text to a temp file beside path and rename it over, so readers never see a torn file.

    The path is resolved first so a symlinked config (stow, chezmoi, `ln -s` into a
    dotfiles repo) keeps its link and the target file receives the change.
    """
    path = os.path.realpath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".opticlaude-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if os.path.exists(path):
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_json(path: str, data: dict) -> None:
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_manifest(scripts_dir: str) -> list[str] | None:
    """Rules setup added on earlier runs, or None when no run has recorded any."""
    path = os.path.join(scripts_dir, MANIFEST)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return list(data.get("deny", [])) if isinstance(data, dict) else []


def save_manifest(scripts_dir: str, rules: list[str]) -> None:
    save_json(os.path.join(scripts_dir, MANIFEST), {"deny": rules})


def install_scripts(target: str, dry_run: bool) -> list[str]:
    names = sorted(n for n in os.listdir(SOURCE_SCRIPTS) if n.endswith(".py"))
    if not dry_run:
        os.makedirs(target, exist_ok=True)
        for name in names:
            dest = os.path.join(target, name)
            shutil.copyfile(os.path.join(SOURCE_SCRIPTS, name), dest)
            os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return names


def add_deny(settings_path: str, rules: list[str], dry_run: bool) -> tuple[list[str], list[str], list[str]]:
    """Add rules to permissions.deny; drop LEGACY_RULES. Returns (added, already present, legacy dropped)."""
    settings = load_settings(settings_path)
    deny = settings.setdefault("permissions", {}).setdefault("deny", [])
    added = [r for r in rules if r not in deny]
    present = [r for r in rules if r in deny]
    dropped = [r for r in deny if r in LEGACY_RULES]
    settings["permissions"]["deny"] = [r for r in deny if r not in dropped] + added
    if (added or dropped) and not dry_run:
        save_json(settings_path, settings)
    return added, present, dropped


def remove_deny(settings_path: str, owned: list[str] | None, dry_run: bool) -> tuple[list[str], list[str]]:
    """Remove the rules setup added (plus legacy ones). Returns (removed, matching rules left alone)."""
    settings = load_settings(settings_path)
    deny = settings.setdefault("permissions", {}).setdefault("deny", [])
    removable = set(LEGACY_RULES) | set(owned or [])
    removed = [r for r in deny if r in removable]
    kept = [r for r in deny if r in DENY_RULES + STRICT_RULES and r not in removable]
    settings["permissions"]["deny"] = [r for r in deny if r not in removed]
    if removed and not dry_run:
        save_json(settings_path, settings)
    return removed, kept


def update_claude_md(path: str, section: str | None, dry_run: bool) -> bool:
    current = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    updated = replace_section(current, section)
    if updated == current:
        return False
    if not dry_run:
        write_atomic(path, updated)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="also deny gh pr view, gh api graphql and gh api repos/*/pulls/* (breaks skills that call them)")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--scripts-dir", default=os.path.join(config_dir(), "scripts", "opticlaude"))
    ap.add_argument("--settings", default=os.path.join(config_dir(), "settings.json"))
    ap.add_argument("--claude-md", default=os.path.join(config_dir(), "CLAUDE.md"))
    args = ap.parse_args()
    tag = " (dry run)" if args.dry_run else ""

    if not os.path.isdir(SOURCE_SCRIPTS):
        print(f"plugin scripts directory missing: {SOURCE_SCRIPTS}", file=sys.stderr)
        return 2

    if args.uninstall:
        owned = load_manifest(args.scripts_dir)
        if os.path.isdir(args.scripts_dir) and not args.dry_run:
            shutil.rmtree(args.scripts_dir)
        print(f"removed {args.scripts_dir}{tag}")
        removed, kept = remove_deny(args.settings, owned, args.dry_run)
        print(f"deny rules removed from {args.settings}{tag}: {len(removed)}")
        for rule in removed:
            print(f"  - {rule}")
        if kept:
            why = "no manifest, cannot tell them from hand-written rules" if owned is None else "not added by setup"
            print(f"left in place ({why}): " + ", ".join(kept))
        changed = update_claude_md(args.claude_md, None, args.dry_run)
        print(f"CLAUDE.md section {'removed' if changed else 'absent'}: {args.claude_md}{tag}")
        return 0

    names = install_scripts(args.scripts_dir, args.dry_run)
    print(f"scripts -> {args.scripts_dir}{tag}: {', '.join(names)}")
    rules = DENY_RULES + (STRICT_RULES if args.strict else [])
    added, present, dropped = add_deny(args.settings, rules, args.dry_run)
    print(f"deny rules added to {args.settings}{tag}: {len(added)} new, {len(present)} already present")
    for rule in added:
        print(f"  + {rule}")
    for rule in dropped:
        print(f"  - {rule}  (overmatching rule from an earlier version, dropped)")
    if added and not args.dry_run:
        owned = load_manifest(args.scripts_dir) or []
        save_manifest(args.scripts_dir, owned + [r for r in added if r not in owned])
    if not args.strict:
        print("skipped (use --strict): " + ", ".join(STRICT_RULES) + "  <- skills that call these directly would break")
    changed = update_claude_md(args.claude_md, claude_md_section(args.scripts_dir), args.dry_run)
    print(f"CLAUDE.md section {'written' if changed else 'unchanged'}: {args.claude_md}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
