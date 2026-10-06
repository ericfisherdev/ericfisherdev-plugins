# Analyze Code City Command

## Contents

- Key Concept
- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to generate a **Code City report** — a stakeholder-friendly visualization of the codebase as a city, where modules are neighborhoods, file complexity is building height, and defect density is the "crime rate." This is designed for non-technical audiences to understand codebase health.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Key Concept

Visualizing a codebase as a city makes abstract quality metrics tangible. Stakeholders can immediately grasp "the Order neighborhood has tall buildings and high crime" without understanding cyclomatic complexity or change coupling.

## Analysis Steps

### 1. Map Neighborhoods (Modules)

**Time window**: Default window: `"6 months ago"`. Use this same value for ALL git log invocations below.

Identify top-level and second-level directories as "neighborhoods":

```bash
find src/ -mindepth 1 -maxdepth 2 -type d
```

Each directory becomes a neighborhood in the city.

### 2. Measure Building Heights (Complexity)

For each file, compute complexity as the "building height":

```bash
wc -l <file>                    # Lines of code = floor count
awk '{ match($0, /^[ \t]*/); depth += RLENGTH } END { if (NR>0) print depth/NR }' <file>  # Nesting = structural complexity
```

**Height tiers:**
| LOC | Height | Visualization |
|-----|--------|--------------|
| < 100 | Low-rise | ▂ |
| 100–250 | Mid-rise | ▅ |
| 250–500 | High-rise | ▇ |
| > 500 | Skyscraper | █ |

### 3. Measure Crime Rates (Defect Density)

For each neighborhood, compute the "crime rate" — the density of defect-related activity:

```bash
git log --since="{since}" --format="%s" --name-only | grep -A1 -iE "fix|bug|patch|hotfix|revert"
```

**Crime rate tiers:**
| Bug Fix Ratio | Crime Rate | Visualization |
|--------------|-----------|--------------|
| < 10% | Safe | 🟢 |
| 10–20% | Moderate | 🟡 |
| 20–35% | High | 🟠 |
| > 35% | Critical | 🔴 |

### 4. Measure Traffic (Change Frequency)

For each neighborhood, compute change frequency as "foot traffic":

```bash
git log --since="{since}" --format='' --name-only | sort | uniq -c | sort -rn
```

Aggregate by directory. High-traffic neighborhoods get more attention and more bugs.

### 5. Measure Population (Contributors)

For each neighborhood, count distinct contributors:

```bash
git log --since="{since}" --format="%aN" --name-only
```

High-population neighborhoods with high crime rates suggest coordination problems.

### 6. Identify City Landmarks

Special features:
- **City Hall**: The main entry point / most-imported module
- **Train Station**: API endpoints (high external traffic)
- **Hospital**: Error handling / logging module
- **University**: Test directories
- **Abandoned Buildings**: Dormant files (> 6 months without changes)

### 7. Compute City Health Score

```
city_health = 100 - (crime_rate_weighted × 30) - (skyscraper_density × 20) - (abandoned_ratio × 20) - (coordination_issues × 30)
```

## Output Format

### Code City Report

**City:** {repo name}
**Population:** {contributor count} developers
**Neighborhoods:** {module count}
**Buildings:** {file count}
**Report period:** {start date} to {current date}

---

### City Skyline

```text
                    █                          
              █     █          ▇               
        ▇     █     █    ▇    ▇     ▅         
  ▅     ▇     █     █    ▇    ▇     ▅    ▂   
  ▅     ▇     █     █    ▇    ▇     ▅    ▂   
┌─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┐
│Auth │Order│Billi│ Api │Email│User │Config│Tests│
│ 🟢  │ 🔴  │ 🟠  │ 🟡  │ 🟢  │ 🟡  │ 🟢  │ 🟢  │
└─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘
```

### Neighborhood Summary

| Neighborhood | Buildings | Height | Traffic | Crime Rate | Population | Health |
|-------------|-----------|--------|---------|-----------|------------|--------|
| `Order/` | 12 | █ Skyscraper | Very High | 🔴 38% | 4 devs | Critical |
| `Billing/` | 8 | ▇ High-rise | High | 🟠 25% | 2 devs | Needs Attention |
| `Api/` | 15 | ▇ High-rise | Very High | 🟡 15% | 5 devs | Fair |
| `Auth/` | 6 | ▅ Mid-rise | Low | 🟢 5% | 2 devs | Good |
| `Email/` | 4 | ▅ Mid-rise | Medium | 🟢 8% | 1 dev | Good |
| `Config/` | 3 | ▂ Low-rise | Low | 🟢 0% | 2 devs | Excellent |

### Neighborhood Deep Dives

For each neighborhood with crime rate 🟠 or 🔴:

---

#### Neighborhood: `Order/` — 🔴 Critical

**The story:** *"The Order district is the busiest part of town with the tallest buildings and the highest crime rate. Four developers work here but coordination is poor — changes frequently break things. The main street (OrderService.php) is a 500-line skyscraper that attracts most of the trouble."*

| Metric | Value |
|--------|-------|
| **Buildings (files)** | 12 |
| **Tallest building** | `OrderService.php` (487 LOC) |
| **Total traffic** | 89 commits |
| **Crime rate** | 38% (34 of 89 commits are fixes) |
| **Residents** | @dev1 (primary), @dev2, @dev3, @dev4 |
| **Abandoned buildings** | 2 files (dormant > 6mo) |

**Tallest buildings (complexity hotspots):**
| Building | Height | Traffic | Crime |
|----------|--------|---------|-------|
| `OrderService.php` | █ 487 LOC | 31 commits | 🔴 42% fixes |
| `OrderRepository.php` | ▇ 320 LOC | 18 commits | 🟠 28% fixes |
| `OrderValidator.php` | ▅ 180 LOC | 15 commits | 🟡 13% fixes |

**Recommendation for city planners:** *"OrderService.php needs to be split into smaller buildings. The current skyscraper tries to do too much. Consider demolishing and rebuilding as 3-4 mid-rise buildings with clear responsibilities."*

---

### City Landmarks

| Landmark | File/Module | Role |
|----------|-------------|------|
| 🏛️ City Hall | `src/Kernel.php` | Application entry point |
| 🚉 Train Station | `src/Infrastructure/Api/` | External API |
| 🏥 Hospital | `src/Infrastructure/Logging/` | Error handling & logging |
| 🏫 University | `tests/` | Test coverage |
| 🏚️ Abandoned Buildings | {count} files | Dormant code (> 6mo) |

### Abandoned Buildings

Files with no activity in 6+ months that still exist in the codebase:

| Building | Neighborhood | Last Activity | Size | Risk |
|----------|-------------|---------------|------|------|
| `src/Legacy/Importer.php` | Legacy | 14 months ago | 420 LOC | 🔴 |
| `src/Util/OldHelper.php` | Utils | 8 months ago | 95 LOC | 🟡 |

### City Growth Trend

How the city has changed over the analysis period:

| Metric | 3 Months Ago | Now | Trend |
|--------|-------------|-----|-------|
| Total buildings | {count} | {count} | {+/−} |
| Skyscrapers (> 500 LOC) | {count} | {count} | {+/−} |
| Overall crime rate | {%} | {%} | {better/worse} |
| Abandoned buildings | {count} | {count} | {+/−} |

### City Health Score

```text
╔══════════════════════════════════╗
║     CITY HEALTH SCORE: {XX}/100  ║
║     Assessment: {Good/Fair/Poor} ║
╚══════════════════════════════════╝
```

| Factor | Score | Weight | Contribution |
|--------|-------|--------|-------------|
| Crime rate (defect density) | {value}/100 | 30% | {value} |
| Skyline (complexity distribution) | {value}/100 | 20% | {value} |
| Abandonment (dormant code) | {value}/100 | 20% | {value} |
| Coordination (parallel dev issues) | {value}/100 | 30% | {value} |

### Executive Summary

*For non-technical stakeholders:*

> **{repo name}** is a city of **{file count} buildings** across **{module count} neighborhoods**, maintained by **{dev count} residents**.
>
> **The good news:** {positive finding — e.g., "Most neighborhoods are safe and well-maintained. The Auth and Config districts are models of good urban planning."}
>
> **The concern:** {main issue — e.g., "The Order district has become overcrowded with tall, complex buildings and a high crime rate. 38% of changes there are fixing previous mistakes. This neighborhood needs investment in infrastructure (refactoring) before adding more features."}
>
> **Recommended investment:** {top action — e.g., "Prioritize splitting the OrderService building and improving test coverage in the Order and Billing districts before the next feature cycle."}


