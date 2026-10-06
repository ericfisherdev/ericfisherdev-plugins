# Analyze Parallel Development Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to detect **parallel development** — files and modules where multiple developers work simultaneously in overlapping time windows — because high parallelism on the same code correlates with higher defect rates.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

When multiple developers modify the same file within a short time window, defect rates increase due to:
- Conflicting assumptions about how the code should behave
- Merge conflicts that get resolved incorrectly
- Incomplete understanding of each other's in-progress changes
- Higher cognitive load from coordinating concurrent work

This is the "many hands" problem — more parallel contributors on a file doesn't mean faster progress, it means more bugs.

## Analysis Steps

### 1. Extract Author-Date-File Data

**Time window**: Default window: `"3 months ago"`.

```bash
git log --since="{since}" --format="AUTHOR:%aN DATE:%ai" --name-only
```

Parse into a list of `(author, date, file)` tuples.

### 2. Define Overlap Windows

**Window size**: Use the `--window` argument if provided, otherwise default to 7 days. Two developers are working "in parallel" on a file if they both commit changes to it within the same window.

Use a sliding window approach:
- For each file, sort commits chronologically
- Slide a `{window}`-day window across the commits
- For each window position, count distinct authors

### 3. Calculate Parallelism Metrics

For each file:

| Metric | Definition |
|--------|-----------|
| **Max parallel authors** | Highest number of distinct authors in any single window |
| **Parallel windows** | Number of windows with ≥ 2 authors |
| **Parallelism ratio** | `parallel_windows / total_windows` (if `total_windows == 0`, set to 0) |
| **Author pairs** | Which specific developers overlapped |

### 4. Score Parallelism Risk

```text
parallelism_risk = max_parallel_authors × parallelism_ratio × commit_count_in_parallel_windows
```

Higher scores indicate sustained parallel development with many contributors.

### 5. Cross-Reference with Defects

Check if high-parallelism files also appear in bug-fix commits:

```bash
git log --since="{since}" --format="%H %s" --name-only --grep="fix\|bug\|revert" -i
```

Files with both high parallelism AND bug fixes confirm the "many hands" problem.

### 6. Identify Coordination Hotspots

A **coordination hotspot** is a file/module where:
- ≥ 3 developers worked in the same window
- The file has above-average complexity
- Bug fixes followed the parallel work period

These are the files that most need better coordination (design discussions, interface contracts, or ownership clarity).

## Output Format

### Parallel Development Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Window size:** {days} days
**Active developers:** {count}

### Parallelism Overview

| Metric | Value |
|--------|-------|
| Files with parallel development | {count} ({percentage}% of active files) |
| Files with ≥ 3 concurrent authors | {count} |
| Coordination hotspots | {count} |
| Average parallelism ratio | {value} |

### Top Parallel Development Files

| Rank | File | Max Authors | Parallel Windows | Parallelism Ratio | Bug Fixes After | Risk |
|------|------|-------------|-----------------|-------------------|-----------------|------|
| 1 | `src/Order/OrderService.php` | 4 | 8 | 0.72 | 3 | 🔴 |
| 2 | `src/Api/UserController.php` | 3 | 6 | 0.55 | 1 | 🟠 |
| 3 | `src/Billing/InvoiceService.php` | 3 | 5 | 0.48 | 0 | 🟡 |

### Detailed Reports

For each coordination hotspot:

---

#### `path/to/file`

| Metric | Value |
|--------|-------|
| **Max concurrent authors** | {count} |
| **Parallel windows** | {count} of {total} |
| **Parallelism ratio** | {value} |
| **Total commits in period** | {count} |
| **Bug fixes following parallel work** | {count} |

**Author Overlap Timeline:**
```text
Week 1:  @dev1 ●●   @dev2 ●        (2 authors)
Week 2:  @dev1 ●    @dev2 ●  @dev3 ●  (3 authors)
Week 3:  @dev2 ●●   @dev3 ●        (2 authors)
Week 4:  @dev1 ●                    (1 author — fix commit)
```

**Developer pairs that overlapped:**
| Author A | Author B | Overlapping Windows | Commits |
|----------|----------|-------------------|---------|
| @dev1 | @dev2 | 4 | 9 |
| @dev1 | @dev3 | 2 | 5 |
| @dev2 | @dev3 | 3 | 7 |

**Post-overlap bug fixes:**
1. `{date}` — "{fix message}" by @{author}
2. `{date}` — "{fix message}" by @{author}

**Assessment:** {e.g., "This file sees regular 3-way parallel development. The fix commits that follow overlap windows suggest coordination issues. Consider assigning a single owner or splitting the file by responsibility."}

---

### Module-Level Parallelism

| Module | Files with Parallelism | Avg Max Authors | Total Overlap Windows |
|--------|----------------------|-----------------|----------------------|
| `src/Domain/Order/` | 5 | 3.2 | 18 |
| `src/Infrastructure/Api/` | 3 | 2.4 | 9 |

### Developer Collision Map

Which developer pairs most frequently work on the same files:

| Developer A | Developer B | Shared Files | Total Overlaps | Resulting Fixes |
|------------|------------|-------------|----------------|-----------------|
| @dev1 | @dev2 | 8 | 14 | 5 |
| @dev1 | @dev3 | 4 | 7 | 2 |

### Summary

| Metric | Value |
|--------|-------|
| Files analyzed | {count} |
| Files with parallel development | {count} |
| Coordination hotspots | {count} |
| Developer pairs with high collision | {count} |
| Bug fixes correlated with parallel work | {count} |

### Recommendations

1. **Ownership clarity**: {file/module needing a single owner}
2. **Interface contracts**: {coupled files where parallel authors need clear boundaries}
3. **Splitting candidates**: {files large enough to split by responsibility to reduce contention}
4. **Process**: {e.g., "When 2+ developers need to modify OrderService.php, schedule a 10-min sync first"}


