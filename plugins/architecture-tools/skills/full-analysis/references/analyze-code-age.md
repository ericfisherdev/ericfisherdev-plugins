# Analyze Code Age Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to map every file by its **age** — when it was last modified — and classify it as either "stable and trusted" or "neglected and risky."

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

Older code isn't inherently bad. Stable, well-tested code that hasn't changed in a year is often the most reliable part of the system. But old code that has no tests, few contributors, and many dependents is a ticking time bomb. The goal is to distinguish between these two cases.

## Analysis Steps

### 1. Map Last-Modified Date for All Files

```bash
git log --format="%ai" --name-only --diff-filter=AMRC | awk '/^[0-9]/ { date=$0 } /^[^0-9]/ && NF { if (!(($0) in files)) files[$0]=date } END { for(f in files) print files[f], f }'
```

This gives the most recent commit date for each file.

### 2. Compute File Age

For each file that still exists on disk, calculate:
- **Age**: Days since last modification
- **Creation date**: First commit that introduced the file
- **Lifespan**: Days from creation to last modification
- **Total lifetime commits**: Number of commits that ever touched the file

### 3. Classify Age Brackets

| Bracket | Age | Label |
|---------|-----|-------|
| 🟢 Fresh | < 30 days | Recently active |
| 🔵 Current | 30–90 days | Moderately recent |
| 🟡 Aging | 90–180 days | Starting to age |
| 🟠 Old | 180–365 days | Significant age |
| 🔴 Ancient | > 365 days | Very old |

### 4. Assess Stability vs. Neglect

For each file in the 🟡/🟠/🔴 brackets, determine if it's **stable** or **neglected**:

#### Signals of Stability (Positive)
- High total lifetime commits (was actively developed, then stabilized)
- Multiple contributors over its lifetime
- Referenced by test files (has test coverage)
- Low complexity (simple, well-factored code)
- Part of a stable module (neighbors also stable)

#### Signals of Neglect (Negative)
- Few lifetime commits (written once, never revisited)
- Single contributor (bus factor = 1)
- No corresponding test file
- High complexity despite age
- Uses deprecated patterns/APIs (if detectable)
- Many dependents (other files import it — high blast radius if it breaks)

#### Scoring
```text
stability_score = lifetime_commits × 0.3 + contributor_count × 0.2 + has_tests × 0.3 + (1/complexity) × 0.2
```
If `complexity == 0` (empty file), use `complexity = 1` as a floor to avoid division by zero.

Normalize to 0–1. Files above 0.6 are "stable"; below 0.4 are "neglected"; between is "uncertain."

### 5. Find Dependents

For files classified as neglected, estimate how many other files depend on them:

```bash
# Search for imports/requires/use statements referencing the file
grep -rl "import.*ClassName\|require.*filename\|use.*Namespace" src/
```

High-dependent neglected files are the highest risk.

### 6. Identify Stale Modules

A module is **stale** if > 70% of its files are in the 🟠/🔴 age brackets. Stale modules may need:
- Active maintainer assignment
- Test coverage audit
- Dependency update review

## Output Format

### Code Age Analysis

**Repository:** {repo name}
**Total files analyzed:** {count}
**Repository age:** {first commit date} to {current date}

### Age Distribution

| Bracket | Files | Percentage | Description |
|---------|-------|------------|-------------|
| 🟢 Fresh (< 30d) | {count} | {%} | Recently active |
| 🔵 Current (30–90d) | {count} | {%} | Moderately recent |
| 🟡 Aging (90–180d) | {count} | {%} | Starting to age |
| 🟠 Old (180–365d) | {count} | {%} | Significant age |
| 🔴 Ancient (> 365d) | {count} | {%} | Very old |

### Stability Classification

| Classification | Files | Description |
|----------------|-------|-------------|
| ✅ Stable | {count} | Mature, trusted code |
| ⚠️ Uncertain | {count} | Needs investigation |
| 🚨 Neglected | {count} | Risky — no recent attention |

### Neglected Files (Highest Risk)

Files that are old, have low stability scores, and high dependent counts:

| Rank | File | Age | Last Author | Stability | Dependents | Risk |
|------|------|-----|-------------|-----------|------------|------|
| 1 | `src/Legacy/Importer.php` | 14mo | @former_dev | 0.18 | 12 files | 🔴 Critical |
| 2 | `src/Util/DateHelper.php` | 11mo | @dev1 | 0.31 | 8 files | 🔴 High |

### Detailed Neglected File Reports

For each top-10 neglected file:

---

#### `path/to/file`

| Metric | Value |
|--------|-------|
| **Last modified** | {date} ({age} ago) |
| **Created** | {date} |
| **Lifetime commits** | {count} |
| **Contributors** | {count} ({list}) |
| **Lines of code** | {count} |
| **Complexity (avg indent)** | {value} |
| **Test coverage** | {Yes/No — based on test file existence} |
| **Files that depend on this** | {count} |
| **Stability score** | {value}/1.0 |

**Neglect signals:**
- {e.g., "Single author, no test file, 8 dependents"}
- {e.g., "Uses deprecated `mysql_*` functions"}

**Risk assessment:** {what could go wrong — e.g., "12 files import this utility. If it breaks, the blast radius spans 3 modules. No tests exist to catch regressions."}

**Recommendation:** {e.g., "Add test coverage as a priority. Assign a current team member as owner."}

---

### Stable Files (Exemplars)

Files that are old but well-maintained — these are the model for how code should age:

| File | Age | Lifetime Commits | Contributors | Has Tests | Stability |
|------|-----|-----------------|--------------|-----------|-----------|
| `src/Core/EventBus.php` | 18mo | 42 | 4 | ✅ | 0.92 |

### Stale Modules

Modules where > 70% of files are old or ancient:

| Module | Files | Avg Age | Stale % | Last Active Contributor |
|--------|-------|---------|---------|------------------------|
| `src/Legacy/` | 15 | 14mo | 93% | @former_dev (inactive) |
| `src/Reports/` | 8 | 9mo | 75% | @dev3 (last commit 3mo ago) |

### Age by Module Heatmap

| Module | 🟢 | 🔵 | 🟡 | 🟠 | 🔴 | Avg Age |
|--------|-----|-----|-----|-----|-----|---------|
| `src/Domain/Order/` | 4 | 2 | 1 | 0 | 0 | 28d |
| `src/Legacy/` | 0 | 0 | 1 | 3 | 11 | 14mo |

### Summary

| Metric | Value |
|--------|-------|
| Total files | {count} |
| Neglected files | {count} ({percentage}%) |
| Neglected with high dependents (≥ 5) | {count} |
| Stale modules | {count} |
| Files with no test coverage AND age > 6mo | {count} |
| Overall codebase freshness | {Fresh / Mixed / Aging / Stale} |

### Recommendations

1. **Critical neglect**: {highest-risk neglected file and action}
2. **Module ownership**: {stale module needing a new owner}
3. **Test gaps**: {old untested files with many dependents}
4. **Process**: {e.g., "Add a quarterly review of files in the 🟠/🔴 brackets"}


