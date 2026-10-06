# Analyze Surprise Changes Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to detect **surprise changes** — commits that touch files outside the author's usual domain, or files that haven't been modified in a long time — because these carry higher defect risk.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

Developers have established domains — modules they work in regularly and understand deeply. When a developer makes changes outside their domain, the defect rate increases because they lack context. Similarly, when a file that's been dormant for months suddenly gets modified, the change is more likely to introduce regressions because the developer may not fully understand the file's invariants and assumptions.

## Analysis Steps

### 1. Build Author Domain Maps

**Time window**: Default window: "3 months ago". The outer historical window for author domain maps uses 2x the window (e.g., if the window is "3 months ago", the domain map looks back "6 months ago"). Use the window value for ALL recent-commit git log invocations below unless otherwise noted.

For each developer, identify their "home modules" based on the outer historical window:

```bash
git log --since="{since_2x}" --format="AUTHOR:%aN" --name-only
```

For each author, compute commit count per module. Their "domain" is any module where they've contributed ≥ 10% of their commits.

### 2. Identify Dormant Files

A file is **dormant** if it hasn't been modified in the last 90 days (configurable):

```bash
comm -23 \
  <(git log --since="{since_2x}" --until="{since}" --format="" --name-only | sort -u) \
  <(git log --since="{since}" --format="" --name-only | sort -u)
```

### 3. Scan Recent Commits for Surprises

For each commit in the analysis window (default: 3 months):

```bash
git log --since="{since}" --format="COMMIT:%H AUTHOR:%aN DATE:%ai MSG:%s" --name-only
```

Flag a commit as a "surprise" if:

#### a. Out-of-Domain Change
The author modified a file in a module that is NOT in their domain map. This means they're working in unfamiliar territory.

#### b. Dormant File Awakening
The commit touches a file that was dormant (no changes in 90+ days). Someone is reviving old code.

#### c. Both (Highest Risk)
An out-of-domain author touching a dormant file — they lack context AND the file hasn't been validated recently.

### 4. Score Surprise Risk

```text
surprise_risk = domain_familiarity_factor × dormancy_factor × change_size_factor
```

| Factor | Low Risk | Medium Risk | High Risk |
|--------|----------|-------------|-----------|
| Domain familiarity | Author's home module | Adjacent module | Unfamiliar module |
| Dormancy | Active (< 30d) | Aging (30–90d) | Dormant (> 90d) |
| Change size | < 10 lines | 10–50 lines | > 50 lines |

### 5. Cross-Reference with Subsequent Fixes

Check if surprise changes were followed by bug-fix commits to the same file within 30 days:

```bash
# For each surprise-changed file, look for fix commits in the following 30 days
git log --since="{surprise_date}" --until="{surprise_date + 30d}" --format="%s" -- <file> | grep -iE "fix|bug|revert"
```

This validates whether surprises actually correlate with defects in this codebase.

## Output Format

### Surprise Change Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Commits analyzed:** {count}
**Surprise commits detected:** {count} ({percentage}%)

### Surprise Type Distribution

| Type | Count | Follow-Up Fixes | Fix Rate |
|------|-------|-----------------|----------|
| Out-of-domain change | {count} | {count} | {percentage}% |
| Dormant file awakening | {count} | {count} | {percentage}% |
| Both (out-of-domain + dormant) | {count} | {count} | {percentage}% |

### Highest-Risk Surprise Changes

| Rank | Commit | Author | File | Type | Risk | Fix Followed? |
|------|--------|--------|------|------|------|---------------|
| 1 | `abc123` | @dev3 | `src/Billing/InvoiceCalc.php` | Both | 🔴 | ✅ (2 fixes) |
| 2 | `def456` | @dev1 | `src/Legacy/DataMigrator.php` | Dormant | 🔴 | ✅ (1 fix) |
| 3 | `ghi789` | @dev2 | `src/Auth/OAuthProvider.php` | Out-of-domain | 🟠 | ❌ |

### Detailed Surprise Reports

For each high-risk surprise:

---

#### Commit `{hash}` — {short message}

| Metric | Value |
|--------|-------|
| **Author** | @{author} |
| **Date** | {date} |
| **Type** | {Out-of-domain / Dormant / Both} |
| **Risk score** | {value} |
| **File** | `{path}` |
| **Change size** | +{added}/−{deleted} lines |
| **File dormancy** | {days} days since last change |
| **Author's domain** | {list of home modules} |
| **Author's familiarity with this module** | {percentage}% of their commits |

**Context:** "{commit message}"

**Why this is a surprise:**
- {e.g., "@dev3 has 0 prior commits in the Billing module. Their domain is Auth and Email."}
- {e.g., "InvoiceCalc.php hadn't been touched in 147 days before this commit."}

**Subsequent fixes:**
- `{date}` `{hash}` — "{fix message}" by @{author}
- `{date}` `{hash}` — "{fix message}" by @{author}

**Assessment:** {e.g., "High risk confirmed — the out-of-domain change to a dormant file resulted in 2 follow-up bug fixes within 2 weeks."}

---

### Dormant Files Recently Awakened

Files that were dormant and have now been modified:

| File | Dormant Since | Awakened By | Awakened On | Domain Match? | Fix Followed? |
|------|--------------|-------------|-------------|---------------|---------------|
| `src/Legacy/DataMigrator.php` | 8 months | @dev1 | {date} | ❌ | ✅ |
| `src/Util/CacheWarmer.php` | 4 months | @dev2 | {date} | ✅ | ❌ |

### Out-of-Domain Activity by Developer

| Author | Out-of-Domain Commits | Modules Ventured Into | Fix Rate After |
|--------|----------------------|----------------------|----------------|
| @dev1 | 5 | Billing, Legacy | 40% |
| @dev3 | 3 | Billing, Order | 67% |

### Surprise Validation

How well do surprises predict defects in this codebase?

| Metric | Value |
|--------|-------|
| Surprise commits with follow-up fixes | {count} ({percentage}%) |
| Non-surprise commits with follow-up fixes | {count} ({percentage}%) |
| **Relative risk** | {surprises are X× more likely to need fixes} |

### Summary

| Metric | Value |
|--------|-------|
| Commits analyzed | {count} |
| Surprise commits | {count} ({percentage}%) |
| Dormant files awakened | {count} |
| Out-of-domain changes | {count} |
| Surprises followed by bug fixes | {count} ({percentage}%) |
| Relative defect risk of surprises | {X}× baseline |

### Recommendations

1. **Review priority**: {list of surprise commits that haven't been thoroughly reviewed}
2. **Knowledge sharing**: {developers frequently venturing out of domain who need context}
3. **Dormant file policy**: {e.g., "Require extra review for changes to files dormant > 90 days"}
4. **Process**: {e.g., "Flag out-of-domain changes in PR reviews for additional scrutiny"}


