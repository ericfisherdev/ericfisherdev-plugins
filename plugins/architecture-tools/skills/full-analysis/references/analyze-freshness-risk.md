# Analyze Freshness Risk Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to identify **freshness risk** — recently modified code has the highest defect rate, and code that's been changed frequently in a short window is the most likely place for the next bug.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

Research shows that recently modified code is far more likely to contain defects than stable code. The more recent and frequent the changes, the higher the risk. This analysis applies a **recency-weighted** scoring model to predict where bugs will appear next.

## Analysis Steps

### 1. Extract Recent Change History

**Time window**: Default window: "3 months ago". Use this same value for ALL git log invocations below.

Get all commits in the analysis window with dates and files:

```bash
git log --since="{since}" --format="COMMIT:%H:%ai" --name-only
```

### 2. Calculate Recency-Weighted Change Score

For each file, weight each commit by how recent it is. More recent changes contribute more to the risk score:

```text
For each commit touching file F:
  days_ago = (today - commit_date).days
  weight = 1 / (1 + days_ago / 7)   # Hyperbolic decay, characteristic time ~1 week

file_score = sum(weight for each commit)
```

This means:
- A commit today has weight ~1.0
- A commit 1 week ago has weight ~0.5
- A commit 1 month ago has weight ~0.19
- A commit 3 months ago has weight ~0.07

### 3. Calculate Change Density

Change density captures how *concentrated* the changes are in time:

```text
change_density = commit_count / max(1, days_between_first_and_last_commit)
```

High density means many changes in a short burst — this correlates with higher defect rates because:
- Rapid successive changes suggest difficulty getting it right
- Less time for testing between changes
- Higher cognitive load on developers

### 4. Compute Composite Risk Score

```text
freshness_risk = (0.5 × recency_weighted_score) + (0.3 × change_density) + (0.2 × author_count_in_window)
```

Multiple authors in a short window increases risk due to potential miscommunication and conflicting assumptions.

### 5. Identify Risk Clusters

Group high-risk files by module. A module with multiple fresh-risk files suggests active, potentially unstable development.

### 6. Cross-Reference with Bug-Fix Commits

Search for commits with "fix", "bug", "patch", "hotfix", "revert" in their messages:

```bash
git log --since="{since}" --format="%H %s" --name-only | grep -A1 -iE "fix|bug|patch|hotfix|revert"
```

Files that appear in both the high-freshness-risk list AND bug-fix commits are **confirmed trouble spots**.

## Output Format

### Freshness Risk Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Commits analyzed:** {count}

### Risk Distribution

| Risk Level | Files | Criteria |
|------------|-------|----------|
| 🔴 Critical | {count} | Freshness score > 80th percentile |
| 🟠 High | {count} | 60th–80th percentile |
| 🟡 Moderate | {count} | 40th–60th percentile |
| 🟢 Low | {count} | Below 40th percentile |

### Top Risk Files

| Rank | File | Risk Score | Recent Commits | Density | Authors | Bug Fixes? |
|------|------|-----------|----------------|---------|---------|------------|
| 1 | `src/Order/OrderService.php` | 8.7 | 14 | 0.82 | 3 | ✅ (4 fixes) |
| 2 | `src/Api/PaymentController.php` | 7.2 | 11 | 0.71 | 2 | ✅ (2 fixes) |
| 3 | `src/Auth/TokenService.php` | 6.5 | 9 | 0.65 | 3 | ❌ |

### Detailed Risk Reports

For each file at 🔴 Critical risk:

---

#### `path/to/file`

| Metric | Value |
|--------|-------|
| **Freshness risk score** | {value} |
| **Commits in window** | {count} |
| **Most recent commit** | {date} ({days} ago) |
| **Change density** | {value} (commits/day) |
| **Authors in window** | {list} |
| **Bug-fix commits** | {count} |
| **Recency-weighted score** | {value} |

**Change timeline:**
```
Week 1:  ●●●      (3 commits)
Week 2:  ●        (1 commit)
Week 3:  ●●●●●    (5 commits — spike)
Week 4:  ●●       (2 commits)
...
```

**Recent commit messages:**
1. `{date}` — "{message}" by @{author}
2. `{date}` — "{message}" by @{author}
3. `{date}` — "{message}" by @{author}

**Bug-fix pattern:** {e.g., "4 of 14 commits are bug fixes, suggesting initial implementation was unstable"}

**Prediction:** {e.g., "High probability of additional defects. The change density and fix-commit ratio suggest the design in this file isn't stable yet."}

---

### Confirmed Trouble Spots

Files with BOTH high freshness risk AND recent bug-fix commits:

| File | Risk Score | Bug Fixes | Fix Ratio | Assessment |
|------|-----------|-----------|-----------|------------|
| `src/Order/OrderService.php` | 8.7 | 4 of 14 | 29% | 🔴 Active bug source |

### Risk by Module

| Module | Avg Risk Score | Critical Files | Recent Bug Fixes |
|--------|---------------|----------------|------------------|
| `src/Domain/Order/` | 6.8 | 3 | 7 |
| `src/Infrastructure/Api/` | 4.2 | 1 | 2 |

### Change Burst Detection

Periods of unusually high commit density that may indicate rushed work:

| Period | Commits | Normal Rate | Actual Rate | Files Affected | Assessment |
|--------|---------|-------------|-------------|----------------|------------|
| Mar 15–22 | 28 | 8/week | 28/week | 12 | 🔴 3.5× normal rate |

### Summary

| Metric | Value |
|--------|-------|
| Files analyzed | {count} |
| Critical risk files | {count} |
| Confirmed trouble spots | {count} |
| Active bug sources (high risk + recent fixes) | {count} |
| Modules with concentrated risk | {count} |

### Recommendations

1. **Test priority**: {files most likely to have undiscovered bugs}
2. **Review priority**: {open PRs touching high-risk files}
3. **Stabilization**: {modules that need a cooling-off period}
4. **Process**: {e.g., "Files with > 3 bug fixes in a month should trigger a design review"}


