# Analyze Off-Pattern Commits Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to detect **off-pattern commits** — commits that deviate significantly from a developer's established behavioral norms — because anomalous commits are statistically more likely to contain defects.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

Every developer has a "normal" — typical commit size, usual working hours, preferred modules, and characteristic change patterns. When a commit breaks these norms (unusually large, at an unusual time, touching unusual files), it often indicates:
- Rushed work under deadline pressure
- Unfamiliar code being modified without full context
- A "dump commit" bundling unrelated changes
- Late-night or weekend fixes suggesting incident response

These anomalous commits carry higher defect risk and deserve extra review scrutiny.

## Analysis Steps

### 1. Build Per-Author Baselines

For each active developer, compute behavioral baselines from the last 6 months:

```bash
git log --since="6 months ago" --format="AUTHOR:%aN DATE:%ai HASH:%H" --numstat
```

#### Baseline Metrics

| Metric | How to Compute |
|--------|---------------|
| **Avg commit size** | Mean of (lines added + lines deleted) per commit |
| **Commit size std dev** | Standard deviation of commit sizes |
| **Avg files per commit** | Mean number of files changed per commit |
| **Usual work hours** | Hour-of-day distribution (identify the 80% window) |
| **Usual work days** | Day-of-week distribution |
| **Home modules** | Modules comprising ≥ 80% of their commits |
| **Avg commits per day** | When active, how many commits per day |

### 2. Score Each Recent Commit

For each commit in the analysis window (default: 3 months), compute deviation scores:

#### a. Size Anomaly
```text
size_z_score = (commit_size - author_avg_size) / author_std_dev
```
If `author_std_dev == 0`, set `size_z_score = 0` (no variance means no anomaly).

Flag if |z-score| > 2.0 (commit is 2+ standard deviations from the author's norm).

#### b. Time Anomaly
Flag commits made outside the author's usual 80% work-hours window (e.g., a developer who normally commits 9am–6pm committing at 2am).

#### c. Spread Anomaly
```text
spread_z_score = (files_changed - author_avg_files) / author_files_std_dev
```
If `author_files_std_dev == 0`, set `spread_z_score = 0`.

Flag if z-score > 2.0 (touching unusually many files).

#### d. Domain Anomaly
Flag commits where > 50% of changed files are outside the author's home modules.

#### e. Frequency Anomaly
Flag days where the author made significantly more commits than their daily average (e.g., 12 commits when their norm is 3).

### 3. Compute Composite Anomaly Score

```text
anomaly_score = max(size_z_score, time_score, spread_z_score, domain_score, frequency_score)
```

Use the maximum rather than average — a single extreme deviation is enough to flag a commit.

### 4. Classify Anomaly Types

| Type | Signal | Common Cause |
|------|--------|-------------|
| **Giant commit** | Size z > 3.0 | Feature dump, missed incremental commits |
| **Midnight commit** | Outside work hours | Incident response, deadline pressure |
| **Shotgun commit** | Spread z > 2.5 | Cross-cutting change or bundled unrelated work |
| **Tourist commit** | Domain score high | Working in unfamiliar code |
| **Commit storm** | Frequency z > 2.0 | Rushing to finish, or catching up after absence |

### 5. Cross-Reference with Bug Fixes

Check if off-pattern commits were followed by fix commits:

```bash
git log --since="{commit_date}" --until="{commit_date + 30d}" --format="%s" -- <files> | grep -iE "fix|bug|revert"
```

### 6. Identify Systemic Patterns

Look for patterns across off-pattern commits:
- Are they concentrated before deadlines?
- Do certain developers have more anomalies?
- Do specific modules attract anomalous commits?

## Output Format

### Off-Pattern Commit Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Commits analyzed:** {count}
**Off-pattern commits detected:** {count} ({percentage}%)

### Anomaly Type Distribution

| Type | Count | Fix Rate | Avg Risk |
|------|-------|----------|----------|
| Giant commit | {count} | {percentage}% | 🔴 |
| Midnight commit | {count} | {percentage}% | 🟠 |
| Shotgun commit | {count} | {percentage}% | 🔴 |
| Tourist commit | {count} | {percentage}% | 🟠 |
| Commit storm | {count} | {percentage}% | 🟡 |

### Top Anomalous Commits

| Rank | Commit | Author | Date | Type | Anomaly Score | Fix Followed? |
|------|--------|--------|------|------|---------------|---------------|
| 1 | `abc123` | @dev1 | {date} | Giant + Shotgun | 4.2 | ✅ |
| 2 | `def456` | @dev3 | {date} 2:30am | Midnight | 3.8 | ✅ |
| 3 | `ghi789` | @dev2 | {date} | Tourist | 3.1 | ❌ |

### Detailed Anomaly Reports

For each top anomalous commit:

---

#### Commit `{hash}` — "{short message}"

**Author:** @{author} | **Date:** {date} {time}

| Metric | Author Baseline | This Commit | Z-Score | Anomaly? |
|--------|----------------|-------------|---------|----------|
| Commit size (lines) | {avg} ± {std} | {value} | {z} | {Yes/No} |
| Files changed | {avg} ± {std} | {value} | {z} | {Yes/No} |
| Time of day | {usual range} | {time} | — | {Yes/No} |
| Domain match | {home modules} | {modules touched} | — | {Yes/No} |
| Daily frequency | {avg}/day | {count}/day | {z} | {Yes/No} |

**Anomaly type:** {Giant / Midnight / Shotgun / Tourist / Storm}
**Composite score:** {value}

**Files changed:**
- `{file1}` (+{added}/−{deleted})
- `{file2}` (+{added}/−{deleted})
- ...

**Why this is anomalous:** {e.g., "@dev1 normally averages 35 lines per commit with 2 files. This commit changed 340 lines across 14 files — a 4.2σ outlier in size and 5.1σ in spread. This suggests a feature dump rather than incremental development."}

**Subsequent fixes:**
- {list any fix commits within 30 days on the same files, or "None detected"}

---

### Per-Developer Anomaly Summary

| Author | Total Commits | Off-Pattern | Anomaly Rate | Most Common Type |
|--------|--------------|-------------|-------------|-----------------|
| @dev1 | 45 | 6 | 13% | Giant commit |
| @dev2 | 38 | 3 | 8% | Tourist |
| @dev3 | 28 | 5 | 18% | Midnight |

### Temporal Patterns

Are anomalies clustered around specific dates?

| Period | Normal Commits | Off-Pattern Commits | Anomaly Rate | Notes |
|--------|---------------|-------------------|-------------|-------|
| Week of {date} | 15 | 6 | 40% | {e.g., "Sprint deadline"} |
| Week of {date} | 22 | 2 | 9% | Normal |

### Anomaly Validation

| Metric | Value |
|--------|-------|
| Off-pattern commits with follow-up fixes | {count} ({percentage}%) |
| Normal commits with follow-up fixes | {count} ({percentage}%) |
| **Relative risk** | Off-pattern commits are {X}× more likely to need fixes |

### Summary

| Metric | Value |
|--------|-------|
| Commits analyzed | {count} |
| Off-pattern commits | {count} ({percentage}%) |
| Most anomalous commit | `{hash}` by @{author} (score: {value}) |
| Developer with highest anomaly rate | @{author} ({percentage}%) |
| Anomaly-to-fix correlation | {X}× baseline risk |

### Recommendations

1. **Review these commits**: {list of high-anomaly commits not yet reviewed}
2. **Process improvement**: {e.g., "Commits with anomaly score > 3.0 should require a second reviewer"}
3. **Deadline pressure**: {if temporal clustering detected, suggest sprint planning adjustments}
4. **Individual coaching**: {developers with high anomaly rates may benefit from pairing or smaller work items}


