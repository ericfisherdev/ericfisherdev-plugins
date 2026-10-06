# Analyze PR Complexity Command

## Contents

- Analysis Steps
- Output Format

You are an expert in behavioral code analysis (per Adam Tornhill's "Software Design X-Rays"). Your task is to **score open pull requests by risk** — based on whether they touch code hotspots, introduce new coupling, or modify high-churn areas — so reviewers can prioritize their attention.

> [!important] Special Instruction
> Requires `gh` CLI authenticated. Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Analysis Steps

### 1. Fetch Open PRs

```bash
gh pr list --state open --json number,title,author,headRefName,additions,deletions,changedFiles,url
```

### 2. For Each PR, Get Changed Files

```bash
gh pr diff <pr-number> --name-only
```

### 3. Build Risk Profile from Git History

Before scoring PRs, compute baseline metrics from git history (last 6 months):

#### a. Hotspot data
```bash
git log --since="6 months ago" --format='' --name-only | sort | uniq -c | sort -rn | head -50
```
Tag the top 20% as "hotspot files."

#### b. Change coupling data
For each commit, extract co-changed file sets. Build a co-change frequency map for file pairs with ≥ 3 co-changes.

#### c. Churn data
```bash
git log --since="6 months ago" --numstat --format="" | awk '/^[0-9]/ { added[$3]+=$1; deleted[$3]+=$2 } END { for(f in added) print added[f]+deleted[f], f }' | sort -rn | head -30
```
Tag the top 20% as "high-churn files."

### 4. Score Each PR

For each PR, compute risk factors:

| Factor | Weight | Criteria |
|--------|--------|----------|
| **Hotspot touches** | 3× | Number of changed files that are hotspots |
| **High-churn touches** | 2× | Number of changed files in high-churn list |
| **Coupling violations** | 3× | Files that are coupled to unchanged files (reviewer should check those too) |
| **Size** | 1× | Total additions + deletions (normalized) |
| **File spread** | 1× | Number of distinct modules/directories touched |
| **New file coupling risk** | 2× | New files added alongside existing coupled files |

```
risk_score = (3 × hotspot_files) + (2 × churn_files) + (3 × coupling_violations) + (1 × normalized_size) + (1 × module_spread)
```

### 5. Identify Missing Review Scope

Using coupling data, check if the PR modifies one file in a coupled pair but NOT the other. Flag these as "coupled files not in PR" — the reviewer should verify those files don't also need changes.

### 6. Classify PR Risk

| Risk Level | Score Range | Recommendation |
|------------|-------------|----------------|
| 🔴 High | Top 20% | Requires thorough review, consider splitting |
| 🟠 Medium | Middle 40% | Standard review with extra attention on flagged files |
| 🟢 Low | Bottom 40% | Standard review |

## Output Format

### PR Complexity Analysis

**Repository:** {repo name}
**Open PRs analyzed:** {count}
**Baseline period:** Last 6 months ({commit count} commits)

### PR Risk Ranking

| Risk | PR | Title | Author | Score | Hotspots | Churn | Coupling | Size |
|------|-----|-------|--------|-------|----------|-------|----------|------|
| 🔴 | #123 | Refactor order flow | @dev1 | 14.2 | 3 files | 2 files | 2 violations | +450/−120 |
| 🟠 | #456 | Add email templates | @dev2 | 7.8 | 1 file | 1 file | 0 | +200/−30 |
| 🟢 | #789 | Fix typo in docs | @dev3 | 0.5 | 0 | 0 | 0 | +2/−2 |

### Detailed PR Reports

For each PR at 🔴 or 🟠 risk:

---

#### PR #{number}: {title}

**Author:** @{author} | **Branch:** `{branch}` | **Risk:** {level}
**Link:** {url}

| Risk Factor | Score | Details |
|-------------|-------|---------|
| Hotspot touches | {score} | {list of hotspot files touched} |
| High-churn files | {score} | {list of high-churn files touched} |
| Coupling violations | {score} | {list of coupled files missing from PR} |
| Size | {score} | +{additions}/−{deletions} across {file count} files |
| Module spread | {score} | {list of modules touched} |

**Coupled files NOT in this PR** (reviewer should check):
- `path/to/coupled_file_a` — coupled with `changed_file_x` (strength: {value})
- `path/to/coupled_file_b` — coupled with `changed_file_y` (strength: {value})

**Review guidance:**
- {specific guidance — e.g., "Focus review on OrderService.php — it's a hotspot with high churn"}
- {e.g., "Verify that BillingService.php doesn't also need changes — it's coupled with OrderService.php"}

---

### Summary

| Metric | Value |
|--------|-------|
| PRs analyzed | {count} |
| High-risk PRs | {count} |
| Medium-risk PRs | {count} |
| Low-risk PRs | {count} |
| Total coupling violations found | {count} |
| PRs touching hotspots | {count} |


