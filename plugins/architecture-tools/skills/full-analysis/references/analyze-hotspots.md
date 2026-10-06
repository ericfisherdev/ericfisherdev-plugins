# Analyze Hotspots Command

## Contents

- Analysis Steps
- Output Format

You are an expert in behavioral code analysis (per Adam Tornhill's "Software Design X-Rays"). Your task is to identify **hotspots** — files that are both frequently changed AND complex — because these are the highest-priority candidates for refactoring.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Analysis Steps

### 1. Determine Time Window

**Time window**: Default window: `"6 months ago"`. Use this same value for ALL git log invocations below.

```bash
git log --since="{since}" --format='' --name-only | sort | uniq -c | sort -rn | head -50
```

This produces a ranked list of files by **change frequency** (number of commits that touched each file).

### 2. Measure Complexity

For each of the top 50 most-changed files that still exist on disk, estimate complexity using a proxy appropriate to the language:

#### Lines of Code (universal fallback)
```bash
wc -l <file>
```

#### Indentation-Based Complexity (better proxy)
Count the average indentation depth — deeper nesting correlates with higher cyclomatic complexity:
```bash
awk '{ match($0, /^[ \t]*/); depth += RLENGTH } END { if (NR>0) print depth/NR }' <file>
```

#### Language-Specific (if tooling is available)
- **PHP**: Look for `phpstan`, `phpmd`, or `php-cs-fixer` in `composer.json`
- **JS/TS**: Look for `eslint` complexity rule output
- **Python**: Look for `radon` or `flake8`

If no tooling is available, use indentation depth + lines of code as the complexity proxy.

### 3. Calculate Hotspot Score

For each file, compute:

```
hotspot_score = change_frequency × complexity_proxy
```

Normalize both factors to 0–1 range before multiplying so neither dominates.

### 4. Filter Out Non-Source Files

Exclude from the final ranking:
- Lock files (`*.lock`, `package-lock.json`, `composer.lock`)
- Generated files (`*.generated.*`, `*.min.*`)
- Migration files (if they follow a timestamp-naming convention)
- Configuration files (`*.yml`, `*.yaml`, `*.json`, `*.xml`) unless they exceed 200 lines
- Test fixtures and snapshots

### 5. Identify Hotspot Clusters

Group hotspots by directory/module to identify **module-level hotspots** — directories where multiple files are individually hot:

```
src/Domain/Order/       — 4 hotspot files (total score: 3.8)
src/Infrastructure/Api/ — 3 hotspot files (total score: 2.1)
```

## Output Format

### Hotspot Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Commits analyzed:** {count}

### Top File Hotspots

| Rank | File | Changes | Complexity | Score | Trend |
|------|------|---------|------------|-------|-------|
| 1 | `src/Order/OrderService.php` | 47 | 0.92 | 0.87 | 🔥 |
| 2 | `src/Api/UserController.php` | 38 | 0.78 | 0.72 | 🔥 |
| 3 | `src/Auth/AuthMiddleware.php` | 31 | 0.85 | 0.68 | ⬆️ |

**Legend:** 🔥 = top 10%, ⬆️ = above median, ➡️ = stable

### Module-Level Hotspots

| Rank | Module/Directory | Hotspot Files | Aggregate Score |
|------|-----------------|---------------|-----------------|
| 1 | `src/Domain/Order/` | 4 | 3.8 |
| 2 | `src/Infrastructure/Api/` | 3 | 2.1 |

### Hotspot Details

For each top-10 hotspot, provide:

---

#### [Rank]. `path/to/file`

| Metric | Value |
|--------|-------|
| **Commits** | {count} in {period} |
| **Distinct Authors** | {count} |
| **Lines of Code** | {count} |
| **Avg Indentation Depth** | {value} |
| **Hotspot Score** | {score} |

**Top Change Reasons** (from commit messages):
1. {most common commit message theme}
2. {second most common}
3. {third most common}

**Recommendation:** {brief recommendation — e.g., "Extract into smaller services", "High churn suggests unclear responsibility boundaries"}

---

### Summary

| Metric | Value |
|--------|-------|
| Files analyzed | {count} |
| Files qualifying as hotspots (top 20%) | {count} |
| Hotspot modules | {count} |
| Recommended refactoring targets | {count} |

### Risk Assessment

- **Critical hotspots** (high change + high complexity): {list}
- **Complexity-only** (complex but stable — low priority): {list}
- **Churn-only** (frequent changes but simple — likely config/boilerplate): {list}


