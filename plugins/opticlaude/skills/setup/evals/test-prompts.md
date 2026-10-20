# Test prompts for setup

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: plain install

> /opticlaude:setup

Expected with skill: a dry run is shown first, then the real run; the summary names the scripts directory, the deny rules added, and the CLAUDE.md block, and says to re-run after plugin updates. The strict rules are not added.

Baseline without skill: scripts copied by hand to an ad hoc path, deny rules written without checking the existing list, CLAUDE.md appended without markers.

## Prompt 2: strict

> Set up opticlaude and block gh pr view too.

Expected with skill: the warning that the `gh pr view`, `gh api graphql` and `gh api repos/*/pulls/*` deny rules break the named skills, then `--strict` is passed only after the user confirms.

Baseline without skill: the rules are added without the warning.

## Prompt 3: uninstall

> Remove everything opticlaude installed.

Expected with skill: `--uninstall` removes the scripts directory, the deny rules recorded in `installed-rules.json` and the CLAUDE.md block, leaving other settings, hand-written deny rules and CLAUDE.md content untouched.

Baseline without skill: manual edits that miss one of the three locations.
