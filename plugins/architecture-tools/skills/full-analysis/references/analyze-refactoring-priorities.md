# Analyze Refactoring Priorities Command

## Contents

- Analysis Steps
- Output Format

You are an expert in behavioral code analysis (per Adam Tornhill's "Software Design X-Rays"). Your task is to produce a **prioritized refactoring backlog** by combining hotspot, change coupling, code churn, and knowledge map signals into a single ranked list of refactoring candidates.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Analysis Steps

### 1. Gather All Signals

Run the data-gathering steps from four analyses in sequence. You do NOT need to produce full reports — just gather the raw metrics.

**Time window**: Default window: `"6 months ago"`. Use this same value for ALL git log invocations below.

#### a. Hotspot data
```bash
git log --since="{since}" --format='' --name-only | sort | uniq -c | sort -rn | head -50
```
For top 50 files, measure complexity (LOC + average indentation depth).

#### b. Churn data
```bash
git log --since="{since}" --numstat --format="" | awk '/^[0-9]/ { added[$3]+=$1; deleted[$3]+=$2 } END { for(f in added) print added[f], deleted[f], f }' | sort -rn
```
Compute churn rate and rewrite ratio for top files.

#### c. Change coupling data
Extract commit-to-file mappings. Identify file pairs with ≥ 3 co-changes. Flag temporal-only couplings (no import relationship).

#### d. Knowledge map data
```bash
git log --since="{since}" --format="%aN" --name-only
```
Compute bus factor per file and per module.

### 2. Score Each File/Module

For each source file that appears in any signal, compute a composite priority score:

| Signal | Weight | Metric | Rationale |
|--------|--------|--------|-----------|
| **Hotspot** | 3× | `change_frequency × complexity` (normalized 0–1) | High-churn complex code is the #1 refactoring target |
| **Churn thrashing** | 2× | `rewrite_ratio` (0–1, where > 0.7 = thrashing) | Repeated rewrites indicate design problems |
| **Coupling violations** | 2× | Count of temporal-only couplings involving this file | Hidden dependencies are architecture debt |
| **Bus factor** | 1× | `1 / bus_factor` (normalized, capped at 1.0) | Single-owner code is harder to refactor later |
| **File size** | 1× | LOC normalized to 0–1 against repo max | Larger files have more surface area for bugs |

```
priority_score = (3 × hotspot) + (2 × thrashing) + (2 × coupling) + (1 × bus_risk) + (1 × size)
```

Maximum possible score: 9.0.

### 3. Aggregate to Module Level

Roll up file-level scores into module/directory scores:
- **Module score**: Sum of all file scores in the module
- **Hotspot density**: Percentage of files in the module that are hotspots
- **Primary signal**: Which factor contributes most to the module's score

### 4. Generate Refactoring Recommendations

For each top candidate, suggest a specific refactoring action based on the dominant signal:

| Dominant Signal | Recommended Action |
|-----------------|-------------------|
| Hotspot (complexity + churn) | Extract smaller classes/functions, simplify conditionals |
| Thrashing (high rewrite ratio) | Stabilize interface, clarify responsibilities, add tests |
| Coupling (temporal dependencies) | Introduce abstraction layer, define explicit contracts |
| Bus factor (single owner) | Document, pair-program, assign reviews to others |
| Size (large file) | Split by responsibility, extract modules |

### 5. Estimate Effort

Provide a rough effort estimate for each recommendation:

| Effort | Criteria |
|--------|----------|
| **S** (Small) | Single file, isolated change, < 1 day |
| **M** (Medium) | Multiple files in one module, 1–3 days |
| **L** (Large) | Cross-module refactoring, 3–5 days |
| **XL** (Extra Large) | Architectural change, > 5 days, needs design review |

## Output Format

### Refactoring Priority Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Commits analyzed:** {count}

### Priority Backlog (Files)

| Rank | File | Score | Hotspot | Churn | Coupling | Bus Factor | Size | Primary Signal |
|------|------|-------|---------|-------|----------|-----------|------|---------------|
| 1 | `src/Order/OrderService.php` | 7.8 | 0.92 | 0.88 | 2 | 1 | 0.65 | Hotspot |
| 2 | `src/Auth/SessionManager.php` | 6.4 | 0.71 | 0.91 | 1 | 1 | 0.48 | Thrashing |
| 3 | `src/Api/UserController.php` | 5.9 | 0.85 | 0.45 | 3 | 2 | 0.72 | Coupling |

### Priority Backlog (Modules)

| Rank | Module | Score | Hotspot Density | Files | Primary Signal |
|------|--------|-------|-----------------|-------|---------------|
| 1 | `src/Domain/Order/` | 18.4 | 60% | 8 | Hotspot + Coupling |
| 2 | `src/Infrastructure/Api/` | 12.1 | 40% | 12 | Churn |

### Refactoring Recommendations

For each top-15 file:

---

#### #{rank}. `path/to/file` — Score: {score}

| Signal | Value | Interpretation |
|--------|-------|----------------|
| Hotspot | {value} | {interpretation} |
| Churn | {value} | {interpretation} |
| Coupling | {value} | {interpretation} |
| Bus factor | {value} | {interpretation} |
| Size | {value} | {interpretation} |

**Recommended refactoring:** {specific action}

**Effort estimate:** {S/M/L/XL}

**Expected benefit:** {what improves — e.g., "Reduces change frequency by isolating calculation logic", "Eliminates hidden coupling to Billing module"}

---

### Signal Summary

| Signal | Files Affected | Most Affected Module |
|--------|---------------|---------------------|
| Hotspot (top 20%) | {count} | {module} |
| Thrashing (rewrite ratio > 0.7) | {count} | {module} |
| Temporal coupling (≥ 3 co-changes) | {count} pairs | {module pair} |
| Bus factor = 1 | {count} | {module} |

### Quick Wins vs. Strategic Refactors

#### Quick Wins (effort S/M, score > 4.0)
| File | Score | Action | Effort |
|------|-------|--------|--------|
| ... | ... | ... | ... |

#### Strategic Refactors (effort L/XL)
| Module | Score | Action | Effort |
|--------|-------|--------|--------|
| ... | ... | ... | ... |

### Summary

| Metric | Value |
|--------|-------|
| Files scoring above threshold | {count} |
| Modules needing attention | {count} |
| Quick wins identified | {count} |
| Strategic refactors identified | {count} |
| Estimated total effort | {sum of effort in days} |


