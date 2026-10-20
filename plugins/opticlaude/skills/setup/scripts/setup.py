#!/usr/bin/env python3
"""Install the opticlaude helper scripts, deny rules and CLAUDE.md pointers.

    setup.py                 install: copy scripts, add deny rules, write the CLAUDE.md section
    setup.py --dry-run       show what would change
    setup.py --strict        also deny `gh pr view` and `gh api graphql` (breaks skills that call them directly)
    setup.py --uninstall     remove the scripts directory, the deny rules and the CLAUDE.md section

Paths (override with flags):
  scripts     ~/.claude/scripts/opticlaude/      stable copy, so the pointers survive plugin version bumps
  settings    ~/.claude/settings.json            permissions.deny gains the rules below
  CLAUDE.md   ~/.claude/CLAUDE.md                a block between <!-- opticlaude:begin --> and <!-- opticlaude:end -->

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

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SOURCE_SCRIPTS = os.path.join(PLUGIN_ROOT, "scripts")
BEGIN, END = "<!-- opticlaude:begin -->", "<!-- opticlaude:end -->"
LEGACY_HEADER = "# Helper Scripts (`~/.claude/scripts/`, run `--help` for usage)"

DENY_RULES = [
    "Bash(sed -n *.d.ts*)",
    "Bash(grep *.d.ts*)",
    "Bash(for f in *cat -n*)",
    "Bash(gh run list *)",
    "Bash(gh api repos/*/pulls/*)",
]
STRICT_RULES = [
    "Bash(gh pr view *)",
    "Bash(gh api graphql *)",
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
        f"- Pull requests: `{d}/pr.py status|checks|threads|resolve|reply [-R owner/repo]`. Prefer it over `gh pr view --json`, `gh run list`, `gh api graphql` review-thread queries and `gh api repos/*/pulls/*`.",
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


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def install_scripts(target: str, dry_run: bool) -> list[str]:
    names = sorted(n for n in os.listdir(SOURCE_SCRIPTS) if n.endswith(".py"))
    if not dry_run:
        os.makedirs(target, exist_ok=True)
        for name in names:
            dest = os.path.join(target, name)
            shutil.copyfile(os.path.join(SOURCE_SCRIPTS, name), dest)
            os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return names


def update_deny(settings_path: str, rules: list[str], remove: bool, dry_run: bool) -> tuple[list[str], list[str]]:
    settings = load_settings(settings_path)
    deny = settings.setdefault("permissions", {}).setdefault("deny", [])
    if remove:
        removed = [r for r in deny if r in DENY_RULES + STRICT_RULES]
        settings["permissions"]["deny"] = [r for r in deny if r not in removed]
        changed, untouched = removed, []
    else:
        changed = [r for r in rules if r not in deny]
        untouched = [r for r in rules if r in deny]
        deny.extend(changed)
    if changed and not dry_run:
        save_json(settings_path, settings)
    return changed, untouched


def update_claude_md(path: str, section: str | None, dry_run: bool) -> bool:
    current = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    updated = replace_section(current, section)
    if updated == current:
        return False
    if not dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(updated)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true", help="also add the gh pr view / gh api graphql deny rules")
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
        if os.path.isdir(args.scripts_dir) and not args.dry_run:
            shutil.rmtree(args.scripts_dir)
        print(f"removed {args.scripts_dir}{tag}")
        removed, _ = update_deny(args.settings, [], remove=True, dry_run=args.dry_run)
        print(f"deny rules removed from {args.settings}{tag}: {len(removed)}")
        changed = update_claude_md(args.claude_md, None, args.dry_run)
        print(f"CLAUDE.md section {'removed' if changed else 'absent'}: {args.claude_md}{tag}")
        return 0

    names = install_scripts(args.scripts_dir, args.dry_run)
    print(f"scripts -> {args.scripts_dir}{tag}: {', '.join(names)}")
    rules = DENY_RULES + (STRICT_RULES if args.strict else [])
    added, present = update_deny(args.settings, rules, remove=False, dry_run=args.dry_run)
    print(f"deny rules added to {args.settings}{tag}: {len(added)} new, {len(present)} already present")
    for rule in added:
        print(f"  + {rule}")
    if not args.strict:
        print("skipped (use --strict): " + ", ".join(STRICT_RULES) + "  <- skills that call these directly would break")
    changed = update_claude_md(args.claude_md, claude_md_section(args.scripts_dir), args.dry_run)
    print(f"CLAUDE.md section {'written' if changed else 'unchanged'}: {args.claude_md}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
