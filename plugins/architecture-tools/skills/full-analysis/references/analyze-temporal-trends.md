# Analyze Temporal Trends Command

## Contents

- Analysis Steps
- Output Format

You are an expert in behavioral code analysis (per Adam Tornhill's "Software Design X-Rays"). Your task is to track **trends over time** — are hotspots getting better or worse? Is coupling increasing? Is churn concentrating? — so the team can see whether their codebase health is improving or degrading.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Analysis Steps

### 1. Define Time Periods

Default: 4 periods, monthly intervals. The user can override with `--periods` and `--interval` (weekly, monthly, quarterly).

Calculate the date boundaries for each period:
```
Period 4 (oldest): 4 months ago → 3 months ago
Period 3:          3 months ago → 2 months ago
Period 2:          2 months ago → 1 month ago
Period 1 (latest): 1 month ago  → now
```

### 2. Compute Metrics Per Period

For each period, gather:

#### a. Hotspot count
```bash
git log --since="{period_start}" --until="{period_end}" --format='' --name-only | sort | uniq -c | sort -rn | head -20
```
Count files that qualify as hotspots (top 20% by change frequency intersected with complexity).

#### b. Total churn
```bash
git log --since="{period_start}" --until="{period_end}" --numstat --format="" | awk '/^[0-9]/ { a+=$1; d+=$2 } END { print a, d }'
```

#### c. Churn concentration
What percentage of total churn is in the top 5 files? High concentration means a few files absorb most change.

#### d. Coupling pairs
Count file pairs with ≥ 3 co-changes within the period (aligned with `--min-coupling=3` default from `analyze-change-coupling`).

#### e. Active contributors
```bash
git log --since="{period_start}" --until="{period_end}" --format="%aN" | sort -u | wc -l
```

#### f. Commit count
```bash
git log --since="{period_start}" --until="{period_end}" --oneline | wc -l
```

#### g. Thrashing files
Count files whose rewrite ratio exceeds a threshold within the period. For each file with churn data in the period:

```
rewrite_ratio = min(lines_added, lines_deleted) / max(lines_added, lines_deleted)
```

A file is "thrashing" if `rewrite_ratio > 0.7` AND total churn (lines added + deleted) ≥ 50 lines. Count thrashing files per period, then normalize against the worst period to produce `thrashing_files_normalized` (used in the health score formula in Step 6).

### 3. Calculate Trend Direction

For each metric, compute the trend across periods:

| Trend | Criteria |
|-------|----------|
| ⬆️ **Increasing** | Latest period > average of prior periods by > 15% |
| ⬇️ **Decreasing** | Latest period < average of prior periods by > 15% |
| ➡️ **Stable** | Within ±15% of prior average |
| 📈 **Accelerating** | Each period higher than the last |
| 📉 **Decelerating** | Each period lower than the last |

### 4. Track Individual File Trajectories

For the top 10 hotspot files, track their change frequency and churn per period. Identify:

- **Emerging hotspots**: Files that weren't hotspots in early periods but are now
- **Cooling hotspots**: Files that were hotspots but activity is decreasing
- **Persistent hotspots**: Files that remain hotspots across all periods

### 5. Coupling Trend

Track whether the number of coupled file pairs is increasing or decreasing. Rising coupling suggests growing architectural complexity.

### 6. Health Score

Compute a composite codebase health score per period:

```
health_score = 100 - (10 × hotspot_count_normalized) - (10 × churn_concentration) - (10 × coupling_pairs_normalized) - (10 × thrashing_files_normalized)
```

Normalize each factor against the worst period. Score range: 0–100, where 100 is ideal.

## Output Format

### Temporal Trend Analysis

**Repository:** {repo name}
**Periods:** {count} ({interval})
**Range:** {oldest period start} to {current date}

### Health Score Trend

```text
100 ┤
 90 ┤
 80 ┤     ●
 70 ┤  ●     ●
 60 ┤           ●
 50 ┤
    └──────────────
      P4   P3   P2   P1
```

| Period | Dates | Health Score | Trend |
|--------|-------|-------------|-------|
| P4 | {dates} | 72 | — |
| P3 | {dates} | 78 | ⬆️ |
| P2 | {dates} | 75 | ⬇️ |
| P1 | {dates} | 63 | ⬇️ |

**Overall trajectory:** {Improving / Stable / Degrading}

### Metric Trends

| Metric | P4 | P3 | P2 | P1 (latest) | Trend |
|--------|-----|-----|-----|-------------|-------|
| Commits | 120 | 135 | 142 | 98 | ⬇️ |
| Hotspot files | 8 | 7 | 9 | 12 | ⬆️ |
| Total churn (lines) | 4,200 | 3,800 | 5,100 | 6,300 | 📈 |
| Churn concentration (top 5) | 35% | 38% | 42% | 51% | 📈 |
| Coupling pairs | 12 | 14 | 13 | 18 | ⬆️ |
| Active contributors | 5 | 6 | 5 | 4 | ⬇️ |
| Thrashing files | 3 | 2 | 4 | 5 | ⬆️ |

### File Trajectories

#### Emerging Hotspots (new in recent periods)

| File | P4 | P3 | P2 | P1 | Assessment |
|------|-----|-----|-----|-----|------------|
| `src/Billing/InvoiceService.php` | 2 changes | 3 | 8 | 14 | 📈 Rapidly emerging |

#### Persistent Hotspots (active across all periods)

| File | P4 | P3 | P2 | P1 | Assessment |
|------|-----|-----|-----|-----|------------|
| `src/Order/OrderService.php` | 12 | 15 | 11 | 13 | ➡️ Persistently hot |

#### Cooling Hotspots (decreasing activity)

| File | P4 | P3 | P2 | P1 | Assessment |
|------|-----|-----|-----|-----|------------|
| `src/Auth/AuthMiddleware.php` | 18 | 12 | 5 | 2 | 📉 Stabilizing |

### Coupling Evolution

| Period | Total Pairs | New Pairs | Dissolved Pairs | Net Change |
|--------|-------------|-----------|-----------------|------------|
| P4 | 12 | — | — | — |
| P3 | 14 | 4 | 2 | +2 |
| P2 | 13 | 1 | 2 | −1 |
| P1 | 18 | 7 | 2 | +5 |

**Coupling trajectory:** {Increasing / Stable / Decreasing}

### Churn Distribution Trend

How churn is distributed across the codebase per period:

| Period | Top 5 files % | Top 10 files % | Rest % |
|--------|--------------|----------------|--------|
| P4 | 35% | 52% | 48% |
| P3 | 38% | 55% | 45% |
| P2 | 42% | 60% | 40% |
| P1 | 51% | 68% | 32% |

**Concentration trajectory:** {Concentrating / Stable / Spreading}

### Key Insights

1. **{Most significant finding}** — {explanation and impact}
2. **{Second finding}** — {explanation}
3. **{Third finding}** — {explanation}

### Recommendations for Next Period

| Action | Rationale | Expected Impact |
|--------|-----------|-----------------|
| {action 1} | {based on which trend} | {expected improvement} |
| {action 2} | {based on which trend} | {expected improvement} |
| {action 3} | {based on which trend} | {expected improvement} |

### Summary

| Metric | Value |
|--------|-------|
| Overall health trajectory | {Improving / Stable / Degrading} |
| Current health score | {value}/100 |
| Biggest concern | {metric with worst trend} |
| Biggest improvement | {metric with best trend} |
| Periods until critical (projection) | {if degrading, estimate when score hits 50} |


