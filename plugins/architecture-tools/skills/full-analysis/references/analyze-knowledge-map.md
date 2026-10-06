# Analyze Knowledge Map Command

## Contents

- Analysis Steps
- Output Format

You are an expert in behavioral code analysis (per Adam Tornhill's "Software Design X-Rays"). Your task is to build a **knowledge map** — mapping who knows what in the codebase by analyzing git history — to identify knowledge silos (bus factor = 1) and diffuse ownership (no clear owner).

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Analysis Steps

### 1. Extract Author-File Ownership Data

**Time window**: Default window: `"12 months ago"`. Use this same value for ALL git log invocations below.

For each source file, determine the primary author and contribution distribution:

```bash
git log --since="{since}" --format="%aN" --name-only
```

Parse this to build a mapping of `file → { author: commit_count }`.

### 2. Calculate Ownership Metrics

For each file, compute:

- **Primary author**: The contributor with the most commits
- **Ownership percentage**: `primary_author_commits / total_commits × 100`
- **Bus factor**: Number of authors who collectively own ≥ 50% of commits (minimum 1)
- **Author count**: Total distinct contributors

### 3. Classify Ownership Patterns

| Pattern | Criteria | Risk |
|---------|----------|------|
| **Single Owner** | One author > 80% of commits | 🔴 High — bus factor = 1 |
| **Dominant Owner** | One author 50–80% of commits | 🟡 Medium — knowledge concentrated |
| **Shared Ownership** | No single author > 50% | 🟢 Healthy — multiple contributors |
| **Diffuse/Abandoned** | 5+ authors, none > 20%, AND last commit > 3 months ago | 🟠 At risk — no clear owner |

### 4. Aggregate by Module/Directory

Roll up individual file ownership into module-level knowledge maps:

```bash
# For each directory, aggregate author contributions across all files
```

A module has a bus factor = 1 if a single developer authored > 70% of changes across all files in that directory.

### 5. Identify Knowledge Silos

A **knowledge silo** exists when:
- A developer is the sole significant contributor to an entire module/directory
- That module is critical (high change frequency or many dependents)
- No other developer has contributed meaningfully in the analysis period

### 6. Identify Knowledge Gaps

A **knowledge gap** exists when:
- A file/module has no commits in the last 6 months
- The primary author is no longer active in the repository (no commits in last 3 months)
- The file is complex (high indentation depth or LOC) with a single historical author

## Output Format

### Knowledge Map Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Active contributors:** {count}
**Files analyzed:** {count}

### Contributor Overview

| Author | Files Touched | Primary Owner Of | Modules | Activity |
|--------|--------------|-----------------|---------|----------|
| @dev1 | 45 | 23 files | Order, Auth | Active |
| @dev2 | 38 | 15 files | Billing, API | Active |
| @dev3 | 12 | 8 files | Reports | Last commit 2mo ago |

### Bus Factor by Module

| Module | Bus Factor | Primary Owner | Ownership % | Risk |
|--------|-----------|---------------|-------------|------|
| `src/Domain/Order/` | 1 | @dev1 | 89% | 🔴 High |
| `src/Infrastructure/Api/` | 3 | @dev2 | 42% | 🟢 Healthy |
| `src/Domain/Billing/` | 1 | @dev2 | 76% | 🟡 Medium |
| `src/Reports/` | 1 | @dev3 | 95% | 🔴 High (inactive) |

### Knowledge Silos (Bus Factor = 1)

---

#### Silo: `module/path/`

| Metric | Value |
|--------|-------|
| **Primary owner** | @developer |
| **Ownership %** | {percentage} |
| **Files in module** | {count} |
| **Total commits** | {count} |
| **Other contributors** | {count} (combined {percentage}%) |
| **Owner still active?** | Yes/No (last commit: {date}) |
| **Module importance** | {High/Medium/Low — based on change frequency and dependents} |

**Risk:** {description of what happens if this developer is unavailable}

**Recommendation:** {e.g., "Schedule pair-programming sessions", "Assign code reviews to spread knowledge", "Document architecture decisions"}

---

### Knowledge Gaps

Files/modules where the primary author is no longer active:

| File/Module | Last Author | Last Commit | Lines | Risk |
|-------------|-------------|-------------|-------|------|
| `src/Legacy/Importer.php` | @former_dev | 8 months ago | 1,200 | 🔴 |

### Ownership Heatmap (Top Files)

| File | Author 1 | Author 2 | Author 3 | Others | Bus Factor |
|------|----------|----------|----------|--------|-----------|
| `OrderService.php` | @dev1 (85%) | @dev2 (10%) | — | 5% | 1 🔴 |
| `UserController.php` | @dev1 (40%) | @dev2 (35%) | @dev3 (20%) | 5% | 3 🟢 |

### Summary

| Metric | Value |
|--------|-------|
| Total active contributors | {count} |
| Files with bus factor = 1 | {count} ({percentage}%) |
| Modules with bus factor = 1 | {count} |
| Knowledge gaps (inactive owner) | {count} |
| Overall repository bus factor | {value} |

### Recommendations

1. **Critical silos**: {list of modules needing immediate knowledge-sharing}
2. **Knowledge gaps**: {list of modules needing new ownership assignment}
3. **Process suggestions**: {e.g., "Rotate code review assignments", "Pair on silo modules monthly"}


