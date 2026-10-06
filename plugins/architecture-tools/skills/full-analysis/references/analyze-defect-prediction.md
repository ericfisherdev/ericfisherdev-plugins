# Analyze Defect Prediction Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to build a **defect probability model** — combining code age, recent change density, author count, complexity trend, and historical bug-fix patterns to predict which files are most likely to contain the next undiscovered bug.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

Defects cluster. Files that have had bugs before are likely to have more. Files with certain characteristics — high complexity, many recent authors, growing size, frequent changes — are statistically more defect-prone. By combining these signals, we can predict *where* to look before bugs are reported.

## Analysis Steps

### 1. Gather Historical Bug-Fix Data

**Time window**: Default window: "6 months ago". Use this same value for ALL git log invocations below.

Identify commits that are bug fixes by searching commit messages:

```bash
git log --since="{since}" --format="HASH:%H MSG:%s" --name-only | awk '
  /^HASH:/ { is_fix = (tolower($0) ~ /fix|bug|patch|hotfix|revert|resolve|correct|repair/) }
  !/^HASH:/ && NF && is_fix { print }
'
```

This awk parser detects commit header lines (`HASH:`), sets a flag when the message matches the bug-fix regex, and prints subsequent non-empty filename lines only while the flag is true — correctly attributing files to their commit.

Build a map of `file → bug_fix_count` — how many bug-fix commits touched each file.

### 2. Compute Defect Signals

For each source file, gather these predictive signals:

#### a. Historical defect density
```text
defect_density = bug_fix_commits / total_commits
```
If `total_commits == 0` for a file, set `defect_density = 0` and skip scoring for that file. Files with a high ratio of fix commits to total commits are inherently defect-prone.

#### b. Code age risk
```bash
# Days since last modification
git log -1 --format="%ai" -- <file>
```
Apply a U-shaped risk curve:
- Very recently modified (< 14 days): HIGH risk (fresh changes haven't been proven)
- Moderately aged (14–180 days): LOW risk (tested in production)
- Very old (> 365 days) with no tests: MEDIUM risk (neglected)

#### c. Author count (recent)
```bash
git log --since="{since}" --format="%aN" -- <file> | sort -u | wc -l
```
More recent authors = higher defect probability (coordination overhead).

#### d. Complexity
Lines of code × average indentation depth (as proxy for cyclomatic complexity).

#### e. Complexity trend
Compare current complexity to complexity 3 months ago. Growing complexity = higher risk.

#### f. Change frequency
```bash
git log --since="{since}" --oneline -- <file> | wc -l
```

### 3. Build Composite Defect Probability Score

```text
defect_probability = 
    (0.25 × defect_density_normalized) +
    (0.20 × recency_risk_normalized) +
    (0.15 × author_count_normalized) +
    (0.15 × complexity_normalized) +
    (0.15 × change_frequency_normalized) +
    (0.10 × complexity_trend_normalized)
```

Normalize all signals to 0–1. The weights reflect research on defect predictors (historical defects are the strongest single predictor).

### 4. Validate Against Known Defects

Cross-reference the top-ranked predictions against actual recent bug-fix commits. Calculate:
- **Precision**: What percentage of top-N predictions had actual bug fixes? (where N = `--top`, default 20)
- **Recall**: What percentage of actual bug-fix files appeared in the top-N?

This self-validation gives confidence in the model's accuracy for this specific codebase.

### 5. Identify Defect Clusters

Group high-probability files by module. Modules with multiple high-probability files suggest systemic design issues rather than isolated bugs.

### 6. Generate Risk Narratives

For each top-risk file, construct a narrative explaining *why* it's likely to have defects, based on which signals contribute most to its score.

## Output Format

### Defect Prediction Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Model signals:** 6 (defect history, recency, authors, complexity, change frequency, complexity trend)

### Prediction Accuracy (Self-Validation)

| Metric | Value |
|--------|-------|
| Historical bug-fix files found | {count} |
| Top-N predictions that had past bugs | {count} ({percentage}%) |
| Bug-fix files captured in top-N | {count} ({percentage}%) |
| Model confidence | {High / Medium / Low} |

### Top Defect Predictions

| Rank | File | Probability | Defect History | Recency | Authors | Complexity | Frequency | Trend |
|------|------|------------|---------------|---------|---------|------------|-----------|-------|
| 1 | `src/Order/OrderService.php` | 0.89 | 0.95 | 0.80 | 0.85 | 0.90 | 0.82 | 0.70 |
| 2 | `src/Api/PaymentController.php` | 0.78 | 0.60 | 0.90 | 0.75 | 0.82 | 0.88 | 0.65 |
| 3 | `src/Auth/TokenService.php` | 0.72 | 0.40 | 0.95 | 0.90 | 0.55 | 0.70 | 0.80 |

### Detailed Prediction Reports

For each top-N predicted file (where N = `--top`, default 20):

---

#### #{rank}. `path/to/file` — Defect Probability: {score}

| Signal | Raw Value | Normalized | Weight | Contribution |
|--------|-----------|------------|--------|-------------|
| Defect history | {X} fix commits / {Y} total | {value} | 0.25 | {value} |
| Recency risk | Last modified {X} days ago | {value} | 0.20 | {value} |
| Author count | {X} authors in 3 months | {value} | 0.15 | {value} |
| Complexity | {X} LOC, {Y} avg indent | {value} | 0.15 | {value} |
| Change frequency | {X} commits in 3 months | {value} | 0.15 | {value} |
| Complexity trend | {+X%} growth | {value} | 0.10 | {value} |

**Dominant risk factor:** {which signal contributes most}

**Risk narrative:** {e.g., "This file has the highest defect density in the codebase (6 of 14 recent commits are fixes), was modified by 4 different developers in the last month, and its complexity has grown 30% in 3 months. The combination of historical defects + many recent hands + growing complexity makes it the most probable location for the next bug."}

**Historical bug patterns:**
1. `{date}` — "{fix commit message}"
2. `{date}` — "{fix commit message}"
3. `{date}` — "{fix commit message}"

**Recommended action:** {e.g., "Prioritize test coverage for the payment calculation paths. Consider a design review to address the growing complexity."}

---

### Defect Clusters (Module Level)

| Module | High-Risk Files | Avg Probability | Total Bug Fixes | Assessment |
|--------|----------------|-----------------|-----------------|------------|
| `src/Domain/Order/` | 4 | 0.76 | 12 | 🔴 Systemic issues likely |
| `src/Infrastructure/Api/` | 2 | 0.65 | 5 | 🟠 Isolated hotspots |

### New vs. Recurring Defect Risk

| Category | Files | Description |
|----------|-------|-------------|
| **Repeat offenders** | {count} | High defect history + high current signals — known trouble spots |
| **Emerging risks** | {count} | Low defect history but high current signals — haven't failed yet but likely will |
| **Healing** | {count} | High defect history but improving current signals — being fixed |

### Testing Priority Queue

Based on predictions, these files should be tested first in the next release:

| Priority | File | Probability | Reason |
|----------|------|------------|--------|
| 1 | {file} | {score} | {dominant signal} |
| 2 | {file} | {score} | {dominant signal} |
| 3 | {file} | {score} | {dominant signal} |

### Summary

| Metric | Value |
|--------|-------|
| Files scored | {count} |
| High probability (> 0.7) | {count} |
| Medium probability (0.4–0.7) | {count} |
| Defect clusters | {count} modules |
| Emerging risks (new, no history) | {count} |
| Model self-validation accuracy | {percentage}% |


