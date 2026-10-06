# Analyze Code Churn Command

## Contents

- Definitions
- Analysis Steps
- Output Format

You are an expert in behavioral code analysis (per Adam Tornhill's "Software Design X-Rays"). Your task is to identify **code churn** — files where the same lines are repeatedly rewritten — because high churn signals design instability rather than healthy evolution.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Definitions

- **Churn**: Lines added + lines deleted in a file across commits. High absolute churn on a file that isn't growing much means lines are being rewritten.
- **Net growth**: Lines added − lines deleted. Low net growth + high churn = thrashing.
- **Churn rate**: `(lines_added + lines_deleted) / current_file_size`. Values > 3.0 mean the file has been rewritten multiple times over.

## Analysis Steps

### 1. Extract Churn Data

For each file, sum lines added and deleted over the analysis period:

```bash
git log --since="6 months ago" --numstat --format="COMMIT:%H" | \
  awk '/^[0-9]/ { added[$3]+=$1; deleted[$3]+=$2 } END { for(f in added) print added[f], deleted[f], f }' | \
  sort -rn -k1,1
```

### 2. Calculate Churn Metrics

For each file, compute:

| Metric | Formula |
|--------|---------|
| **Total churn** | `lines_added + lines_deleted` |
| **Net growth** | `lines_added - lines_deleted` |
| **Churn rate** | `total_churn / current_file_size` |
| **Rewrite ratio** | `min(lines_added, lines_deleted) / max(lines_added, lines_deleted)` |
| **Commit count** | Number of commits touching the file |
| **Churn per commit** | `total_churn / commit_count` |

A **rewrite ratio** close to 1.0 means lines are being replaced rather than simply added or removed — this is the strongest signal of thrashing.

### 3. Classify Churn Patterns

| Pattern | Criteria | Interpretation |
|---------|----------|----------------|
| **Thrashing** | High churn + low net growth + rewrite ratio > 0.7 | 🔴 Same code rewritten repeatedly — likely a design problem |
| **Active Development** | High churn + high net growth | 🟢 New feature being built — healthy |
| **Refactoring** | Moderate churn + negative net growth | 🟡 Code being simplified — usually healthy |
| **Stable** | Low churn relative to file size | ✅ Mature, stable code |

### 4. Identify Thrashing Files

Files with the highest rewrite ratios combined with many commits are the priority concern. These suggest:
- Unclear requirements causing rework
- Poor interface design requiring frequent adaptation
- Shared mutable state causing ripple changes
- A responsibility that doesn't have a clear home

### 5. Churn Concentration Analysis

Check whether churn is concentrated in specific functions/methods or spread across the whole file:

```bash
git log --since="6 months ago" -p -- <file> | grep "^@@" | sort | uniq -c | sort -rn
```

This reveals which sections of the file are churning most, using the diff hunk headers.

## Output Format

### Code Churn Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Commits analyzed:** {count}

### Top Churning Files

| Rank | File | Churn | Net Growth | Churn Rate | Rewrite Ratio | Commits | Pattern |
|------|------|-------|------------|------------|---------------|---------|---------|
| 1 | `src/Order/OrderService.php` | 1,240 | +12 | 4.2 | 0.94 | 31 | 🔴 Thrashing |
| 2 | `src/Api/UserController.php` | 980 | +320 | 2.1 | 0.45 | 22 | 🟢 Active Dev |
| 3 | `src/Auth/SessionManager.php` | 650 | −80 | 3.8 | 0.87 | 18 | 🔴 Thrashing |

### Thrashing Files (Detailed)

For each file classified as "Thrashing":

---

#### `path/to/file`

| Metric | Value |
|--------|-------|
| **Total churn** | {lines_added + lines_deleted} |
| **Net growth** | {lines_added - lines_deleted} |
| **Current size** | {lines} |
| **Churn rate** | {value} |
| **Rewrite ratio** | {value} |
| **Commits** | {count} |
| **Distinct authors** | {count} |
| **Period** | {first change} to {last change} |

**Most-churned sections** (from diff hunk analysis):
1. `lines 42–78` — {function/method name if identifiable} — {churn count} rewrites
2. `lines 120–145` — {function/method name} — {churn count} rewrites

**Commit message themes:**
1. {most common theme — e.g., "fix order calculation"}
2. {second theme}

**Diagnosis:** {hypothesis for why this file churns — e.g., "This service handles both validation and persistence, leading to changes from two different concern streams"}

**Recommendation:** {e.g., "Split into OrderValidator and OrderPersistence", "Stabilize the interface before further changes"}

---

### Churn by Module

| Module | Total Churn | Thrashing Files | Avg Rewrite Ratio |
|--------|-------------|-----------------|-------------------|
| `src/Domain/Order/` | 3,200 | 3 | 0.82 |
| `src/Infrastructure/Api/` | 1,800 | 1 | 0.56 |

### Summary

| Metric | Value |
|--------|-------|
| Files analyzed | {count} |
| Thrashing files (rewrite ratio > 0.7) | {count} |
| Total lines churned | {count} |
| Highest churn rate | {file}: {value} |
| Modules with concentrated churn | {count} |

### Recommendations

1. **Immediate attention**: {top thrashing file and recommended action}
2. **Design review needed**: {module with multiple thrashing files}
3. **Process suggestion**: {e.g., "Add design review step before implementing changes to Order module"}


