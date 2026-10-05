# Test prompts for add-rfp

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: new RFP from a URL

> Add this RFP to the requirements lists: https://example.gov/DocumentCenter/View/12345/Recreation-Software-RFP (City of Example, Parks & Recreation).

Expected with skill: downloads the PDF into `original_files/` under the `<Organization> - <title> <number> (<year>)` name, confirms it is a real PDF, converts it, then spawns an extraction subagent that writes only `orgs/<slug>.json`. The main session runs `module_tool.py validate` and the spot-check command itself, then maps with one subagent, runs `render.py` and `check_links.py`, and ends with the report in the fixed shape.

Baseline without skill: summarizes the PDF in chat or writes a one-off list, does not touch the pipeline, no mapping to the shared catalog, no re-render of the Obsidian notes.

## Prompt 2: missing attachment for an RFP already in the set

> Here is the requirements spreadsheet for the Delaware RFP: ~/Downloads/Delaware Exhibit C Requirements.xlsx. Add it.

Expected with skill: recognises the org already exists in `orgs/*.json`, uses extend mode (adds rows with ids `<SHORT>-<source number>`, drops body requirements the sheet now covers, updates `requirement_sections` and `notes`), deletes the stale mapping entries with the scripted command, then validates, maps, and re-renders.

Baseline without skill: creates a separate new org entry or a standalone summary, leaving stale or duplicated requirements and no mapping clean-up.

## Prompt 3: attachment referenced but not obtainable

> /add-rfp ~/Downloads/Pinellas RFP.pdf

Expected with skill: extracts the body requirements, finds the PDF refers to a separate requirements file that was not supplied, searches for it (WebSearch, sibling file ids on the same host), and when it is not found lists the link in the manual-download list in the final report instead of guessing its contents.

Baseline without skill: reports the body text only and does not mention the missing matrix, or invents requirements for it.
