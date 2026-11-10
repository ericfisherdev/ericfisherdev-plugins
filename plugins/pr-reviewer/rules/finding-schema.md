# Finding schema

Every agent writes one JSON file with the Write tool, at the path its dispatch names, and replies with a count only. The files are read by a program: no prose around the JSON, no code fence, no trailing commas.

## Enumerations

- `severity`: `critical`, `major`, `minor`, `nit`
- `category`: `correctness`, `security`, `data-integrity`, `error-handling`, `performance`, `compatibility`, `deploy`, `test-coverage`, `maintainability`, `docs`, `style`

## Reviewers and lenses: `raw/<name>.json`

```json
{
  "findings": [
    {
      "file": "src/orders/handler.py",
      "line": 88,
      "start_line": null,
      "severity": "major",
      "blocking": true,
      "category": "error-handling",
      "title": "An unparseable quantity is saved as zero",
      "claim": "What is wrong, in one or two sentences, naming the identifiers involved.",
      "trigger": "The concrete input or state that reaches it, and what then happens.",
      "evidence": [
        {"file": "src/orders/handler.py", "line": 88, "note": "what this line shows"},
        {"file": "src/orders/service.py", "line": 41, "note": "the caller that saves the order without checking"}
      ],
      "fix": "What to change, in prose. Null when you have no specific fix.",
      "suggestion": null,
      "confidence": 85,
      "rule": null
    }
  ]
}
```

- `file` is the path as the diff header shows it. `line` is a line number in the new version of the file; for a deletion, the nearest surviving line.
- `start_line` is set only when the finding covers a contiguous range inside one hunk; it is less than `line`.
- `evidence` lists every location the claim depends on, including ones outside the diff. A finding with no evidence entry is discarded.
- `suggestion` is the exact replacement text for lines `start_line` through `line` (or `line` alone), or null. Give one only when it is a complete drop-in replacement you checked against the surrounding code. Never a sketch.
- `rule` quotes the written convention the finding rests on and the file it is in, or null.
- No findings: `{"findings": []}`.

## Verifier: `verified.json`

```json
{
  "summary": "One or two sentences on what the PR does and what the review found. No praise.",
  "findings": [
    {
      "key": "unparseable-quantity-saved-as-zero",
      "file": "src/orders/handler.py",
      "line": 88,
      "start_line": null,
      "severity": "major",
      "blocking": true,
      "category": "error-handling",
      "title": "An unparseable quantity is saved as zero",
      "body": "The comment text, written per comment-style.md.",
      "suggestion": null,
      "sources": ["defect-reviewer", "reach-lens"],
      "checked": "handler.py:80-95, service.py:36-50: the service saves whatever quantity it is given."
    }
  ],
  "dropped": [
    {
      "key": "retry-count-hardcoded",
      "title": "Retry count is hardcoded",
      "file": "src/orders/client.py",
      "line": 12,
      "reason": "Unchanged by this diff; identical on the base branch.",
      "disposition": "dropped"
    }
  ]
}
```

- `key` is a short kebab-case name for the defect itself, stable across passes: the same defect gets the same key next time. It is unique per file.
- `sources` names the agents whose candidates were merged into the finding.
- `checked` says which lines the verifier read and what they showed.
- `dropped[].disposition` is always `dropped`; `reason` is required.

## Refuter: `refuted.json`

```json
{
  "verdicts": [
    {
      "key": "unparseable-quantity-saved-as-zero",
      "file": "src/orders/handler.py",
      "verdict": "downgraded",
      "severity": "minor",
      "blocking": false,
      "reason": "service.py:44 rejects a zero quantity before saving, so the only effect is the error message.",
      "checked": "service.py:36-50"
    }
  ]
}
```

- One verdict per blocking finding. `verdict` is `stands`, `downgraded` or `refuted`.
- `severity` and `blocking` are required for `downgraded` and ignored otherwise.
