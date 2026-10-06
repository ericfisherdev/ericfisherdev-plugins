# Analyze Complexity Trends Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to track how individual files' **complexity changes commit-over-commit** — identifying files on an upward complexity trajectory before they become full hotspots.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

Hotspot analysis shows you what's already complex and frequently changed. Complexity trend analysis is an **early warning system** — it catches files whose complexity is *growing* even if they aren't yet in the danger zone.

## Analysis Steps

### 1. Identify Candidate Files

**Time window**: Default window: "6 months ago". Use this same value for ALL git log invocations below.

Start with files that have had at least 5 commits in the analysis period:

```bash
git log --since="{since}" --format='' --name-only | sort | uniq -c | sort -rn | awk '$1 >= 5 { print $2 }'
```

### 2. Measure Complexity at Each Commit

For each candidate file, sample complexity at regular intervals across the analysis period. Use 4–6 sample points (e.g., monthly snapshots):

```bash
# Get commits that touched the file, ordered chronologically
git log --since="{since}" --format="%H %ai" --follow -- <file> | tac
```

For each sampled commit, checkout the file at that revision and measure complexity:

```bash
# Get file content at a specific commit
git show <commit>:<file> | wc -l          # Lines of code
git show <commit>:<file> | awk '{ match($0, /^[ \t]*/); depth += RLENGTH } END { if (NR>0) print depth/NR }'  # Avg indentation
```

### 3. Calculate Trend Direction

For each file, fit a simple linear trend through the complexity samples:

| Trend | Criteria | Risk |
|-------|----------|------|
| 📈 **Growing** | Latest sample > first sample by > 20%, consistent upward movement | 🔴 File is degrading |
| 📊 **Accelerating** | Growth rate increasing between successive samples | 🔴 Degradation is speeding up |
| ➡️ **Stable** | Complexity within ±10% across all samples | 🟢 Healthy |
| 📉 **Improving** | Latest sample < first sample by > 10% | 🟢 Being cleaned up |
| 🔀 **Volatile** | Complexity swings up and down > 20% between samples | 🟡 Unstable — may indicate competing changes |

### 4. Calculate Growth Rate

```text
growth_rate = (latest_complexity - earliest_complexity) / earliest_complexity × 100
```
If `earliest_complexity == 0` (empty file initially), skip the growth rate calculation or treat as "new file -- no trend data".

Also compute **velocity** — the rate of change between the two most recent samples — to catch recent acceleration.

### 5. Correlate with Change Patterns

For files with growing complexity, check:
- **Author concentration**: Is one developer driving the growth, or is it distributed?
- **Commit message themes**: What kind of work is increasing complexity? (features, fixes, workarounds)
- **Growth source**: Are new functions being added, or are existing functions getting larger?

### 6. Project Forward

For files with consistent upward trends, estimate when they'll cross critical thresholds:
- **200 LOC** for a single function/method (if measurable)
- **500 LOC** for a file (language-dependent — adjust for context)
- **Average indentation depth > 4** (deep nesting)

## Output Format

### Complexity Trend Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Files tracked:** {count} (with ≥ 5 commits)

### Complexity Trajectory Summary

| Status | Count | Description |
|--------|-------|-------------|
| 📈 Growing | {count} | Complexity increasing — action needed |
| 📊 Accelerating | {count} | Growth rate increasing — urgent |
| ➡️ Stable | {count} | Healthy, consistent complexity |
| 📉 Improving | {count} | Being cleaned up |
| 🔀 Volatile | {count} | Unstable swings |

### Files with Growing Complexity

| Rank | File | Start LOC | Current LOC | Growth | Velocity | Trend | Risk |
|------|------|-----------|-------------|--------|----------|-------|------|
| 1 | `src/Order/OrderService.php` | 180 | 340 | +89% | +15%/mo | 📊 | 🔴 |
| 2 | `src/Api/PaymentController.php` | 120 | 195 | +63% | +8%/mo | 📈 | 🔴 |
| 3 | `src/Auth/TokenValidator.php` | 85 | 130 | +53% | +12%/mo | 📈 | 🟡 |

### Detailed Trend Reports

For each file with growing or accelerating complexity:

---

#### `path/to/file`

**Complexity Trajectory:**

```text
LOC
340 ┤                          ●
300 ┤                    ●
260 ┤              ●
220 ┤        ●
180 ┤  ●
    └──────────────────────────
     M1    M2    M3    M4    M5
```

| Sample | Date | LOC | Avg Indent | Change |
|--------|------|-----|------------|--------|
| M1 | {date} | 180 | 2.8 | — |
| M2 | {date} | 220 | 3.1 | +22% |
| M3 | {date} | 260 | 3.3 | +18% |
| M4 | {date} | 300 | 3.5 | +15% |
| M5 | {date} | 340 | 3.8 | +13% |

| Metric | Value |
|--------|-------|
| **Total growth** | +89% |
| **Monthly velocity** | +15% |
| **Trend** | 📊 Accelerating |
| **Primary authors** | @dev1 (60%), @dev2 (30%) |
| **Commit themes** | "add validation", "handle edge case", "fix calculation" |
| **Projected 500 LOC by** | {estimated date} |

**Diagnosis:** {e.g., "This file is accumulating validation logic that should be extracted. The 'handle edge case' pattern in commit messages suggests unclear requirements leading to incremental patching."}

**Recommendation:** {e.g., "Extract validation into a dedicated OrderValidator class before the next feature addition"}

---

### Volatile Files

Files with complexity that swings significantly between samples:

| File | Min LOC | Max LOC | Swing | Samples |
|------|---------|---------|-------|---------|
| `src/Config/Routes.php` | 120 | 210 | 75% | 📈📉📈📉 |

**Interpretation:** {e.g., "Large additions followed by cleanup refactors — indicates a cycle of quick-and-dirty changes followed by cleanup sprints"}

### Early Warning List

Files not yet critical but on trajectory to become problems within 3 months:

| File | Current LOC | Projected LOC (3mo) | Current Risk | Projected Risk |
|------|-------------|---------------------|--------------|----------------|
| `src/Billing/Invoice.php` | 280 | 380 | 🟡 Medium | 🔴 High |

### Summary

| Metric | Value |
|--------|-------|
| Files analyzed | {count} |
| Growing complexity | {count} ({percentage}%) |
| Accelerating complexity | {count} |
| Improving files | {count} |
| Estimated time to critical (worst file) | {timeframe} |

### Recommendations

1. **Urgent**: {accelerating file — specific action}
2. **Preventive**: {growing file — specific action}
3. **Process**: {e.g., "Add complexity gate to CI — fail PRs that increase a file beyond 400 LOC"}


