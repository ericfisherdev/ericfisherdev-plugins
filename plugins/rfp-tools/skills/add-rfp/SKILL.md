---
name: add-rfp
description: Add one or more park/recreation software RFPs to the cross-linked RFP requirements research — download or locate the PDF (and any separate requirements spreadsheet), convert it, extract its requirements, map them to the shared feature catalog with backfill, and re-render every Obsidian RFP note and the most-common-features ranking. Use when the user says "add this RFP", "add these RFPs", "/add-rfp", gives an RFP PDF/URL to include in the requirements lists, or supplies a missing requirements attachment for an RFP already in the set.
argument-hint: '<pdf|xlsx path or URL> [more paths/URLs...] [--org "Name"] [--short ABBR]'
---

# Add an RFP to the requirements research

Pipeline home: `/home/esfisher/dev/literecphp/research/rfp_requirements/` (call it `$P`).
Sources: `/home/esfisher/dev/literecphp/research/original_files/`. Text: `.../research/markdown_conversion/<stem>/`.
Notes (generated, never hand-edited): vault `LiteRecAdmin/research/RFP Requirements/`.

Before starting, read `$P/README.md`, `$P/EXTRACT.md`, `$P/MAP.md`. They are the source of truth; this
skill only sequences them. The main session orchestrates and verifies; extraction and mapping run in
subagents so long RFP text never enters the main context.

## 1. Intake

For each argument:

- **URL** → download with `curl -sSL -A "Mozilla/5.0 (X11; Linux x86_64) Chrome/126"` into `original_files/`
  and confirm with `file` that it is a PDF/XLSX, not an HTML block page (403s and login walls are
  common; if blocked, give the user the link to download manually and stop for that item).
- **Name the file** `<Organization short form> - <RFP title> <number> (<year>).<ext>` — marker names the
  conversion folder after the stem, and the stem appears in the notes.
- **Identify the agency** from `pdftotext -l 2 -layout <pdf> -`.
- **Existing RFP?** `grep -l '"organization"' $P/orgs/*.json` and compare names/RFP numbers. If the
  file is a missing attachment for an RFP already in the set (e.g. its requirements spreadsheet), it
  **extends that org's JSON** rather than creating a new one (step 3, "extend" mode).
- **Separate requirements matrix?** `pdftotext -layout <pdf> - | grep -niE "separate (excel|spreadsheet|file|document)|attachment|exhibit|appendix" | head -40`.
  Many RFPs (Albany Exhibit G, Norman A2, Walnut Creek Attachment A, Delaware, Pinellas, Iowa,
  EBRPD) keep the real requirement list in a separate file. If one is referenced and not supplied:
  WebSearch `"<agency>" "<RFP number>" "<attachment name>"`, and probe the PDF's own URL folder for
  sibling files. Sequential-id hosts leak attachments next to the RFP: CivicPlus `DocumentCenter/View/<id>`
  (probe ids ±10 and read `content-disposition` — Redmond's A/B were 21844/21843 beside RFP 21842) and
  Utah PMN `utah.gov/pmn/files/<id>.<ext>` (Oquirrh's xlsx was 995645 beside PDF 995643; try
  pdf/xlsx/docx). Attachments may be `.docx` too — `convert.sh` handles pdf, xlsx and docx. Download it if found (verify it holds requirements, not just pricing — Delaware's
  Appendix C was pricing only). If not found, record the link/page for the user's manual-download list.

## 2. Convert

```bash
cd $P && ./convert.sh --text-only        # layout text in seconds; extraction reads this
```

Then start `./convert.sh` with `run_in_background` for the marker `.md` files (slow: 15 s to 35 min
per PDF). Extraction does not wait for it. If marker hangs, the script's watchdog handles the
llama-server connection-error loop; never `pkill -f` a pattern that matches your own command.

## 3. Extract (subagent per RFP, parallel OK)

Pick `slug` (kebab-case) and `short` (uppercase letters/digits) unique against
`python3 -c "import json,glob;print(sorted(json.load(open(p))['short'] for p in glob.glob('$P/orgs/*.json')))"`.

Spawn one `general-purpose` subagent per RFP (`model: sonnet`, background; a >100-page RFP gets its own
agent). Prompt:

> Extract the software requirements from a park/recreation RFP into structured JSON.
> Read these two files first and follow them exactly: `$P/EXTRACT.md` (the spec) and `$P/modules.json`
> (module keys and their scope). Input: `<layout.txt path(s)>` (pdftotext -layout, pages separated by form
> feed; or a tab-separated xlsx dump with one "=== Sheet ===" block per sheet — then page is null).
> Locate the requirement sections first (grep requirement/specification/shall/must/Attachment/Appendix/
> "Y or N", read the table of contents), then transcribe every requirement page by page. Do not skim or
> sample; completeness and verbatim text matter. Build the JSON with a small Python script, validate with
> `python3 -m json.tool`, check ids are unique.
> Write ONLY `$P/orgs/<slug>.json` with slug "<slug>", short "<SHORT>", organization "<name>",
> agency_type "<type>", state "<ST>"<, rfp_year/rfp_number if known>. <Say which sections hold the
> requirements if you know; say which files are attachments-only and must be noted in "notes".>
> Do not create or modify any other files.
> Final reply under 100 words: requirement count, page range(s) extracted, and anything a reader should
> know (e.g. a requirements matrix referenced but not included).

**Extend mode** (attachment for an existing RFP): resume or spawn an agent to add the new rows to the
existing `orgs/<slug>.json`, ids `<SHORT>-<source number>` (add a sheet code if numbering restarts per
sheet), drop body requirements the attachment now covers more specifically, update
`requirement_sections` and `notes`. Afterwards the dropped ids leave stale mapping entries —
`module_tool.py check` lists them as "mapping for X which is not in this module"; delete those entries.

When an agent reports a referenced-but-missing attachment, go back to step 1's search for it.

**Verify every file yourself** (do not trust the agent's report):

```bash
cd $P && python3 module_tool.py validate           # must end "0 problems"
```

Then spot-check three random requirements: grep a distinctive phrase from each in the layout text,
and confirm the id and page are right. Also check the id prefix matches the assigned short; fix
mechanically with a Python rename if an agent invented its own prefix (Ohio used OHIO- for OH).

## 4. Map (one subagent, sequential — never parallel with other mapping writers)

Snapshot first: `cp $P/common_features.csv <scratchpad>/common_features.before.csv` and
`tar czf <scratchpad>/rfp_data_before.tgz -C $P orgs catalog mappings`.

Spawn one `general-purpose` agent (default model; judgment matters here). Prompt:

> Map newly added RFP requirements into the canonical feature catalog.
> Working dir `$P`. Read MAP.md (spec, Tools, Rules, "Adding an RFP later") and modules.json first.
> You are the only agent writing catalog/ and mappings/ now.
> New RFP(s): <slugs>. For every module key in modules.json:
> 1. `python3 module_tool.py dump <module> --unmapped` lists requirements with no mapping.
> 2. Read catalog/<module>.json; map each to 1–3 existing features of that module. Add a feature only when
>    nothing fits. **Backfill**: for every feature you add, `python3 module_tool.py dump <module>` and add
>    its key to every other RFP's requirement that also expresses it, so older RFPs link to the new one.
> 3. If a new-RFP requirement is clearly in the wrong module, `python3 module_tool.py move <id> <module>`
>    and map it there. Do not move other RFPs' requirements.
> 4. `python3 module_tool.py check <module>` must report 0 problems and 0 unused for every module.
> Edit only catalog/*.json and mappings/*.json (plus `move`). Apply edits with a Python script
> (json.dump indent=2, ensure_ascii=False). Never rename or delete a key that has mappings.
> Final reply under 100 words: requirements mapped, features added (names), backfilled requirement count,
> requirements moved.

Verify: loop `python3 module_tool.py check <module>` over all modules; each must end
`0 unused), 0 problems`.

## 5. Render and check

```bash
cd $P && python3 render.py && python3 check_links.py
```

`render.py` must print no `WARNING`; `check_links.py` must report `0 broken`.

## 6. Report to the user

- Per new RFP: requirement count, how many are shared with at least one other RFP (note frontmatter
  `shared_requirement_count`), note name (`<SHORT> RFP`).
- Features added and backfilled requirements.
- Ranking changes: diff `common_features.before.csv` against `$P/common_features.csv` (new entries in
  the top 25, rank moves ≥ 3, new features).
- Manual-download list: every referenced-but-unobtainable attachment, with link.
- Marker conversion status (still running in background, or done).

If anything fails midway, the tarball from step 4 restores `orgs/`, `catalog/` and `mappings/`.
