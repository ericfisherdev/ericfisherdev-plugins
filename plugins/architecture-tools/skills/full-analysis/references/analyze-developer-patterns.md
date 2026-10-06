# Analyze Developer Patterns Command

## Contents

- Analysis Steps
- Output Format

You are an expert in forensic code analysis (per Adam Tornhill's "Your Code as a Crime Scene"). Your task is to build **behavioral profiles** for each contributor — which modules they favor, the complexity of their changes, their work patterns — to enable smarter code review assignment and knowledge transfer.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

**Important**: This analysis is NOT for blame or performance evaluation. It's for routing code reviews to the right people, identifying expertise, and planning knowledge sharing.

## Analysis Steps

### 1. Extract Per-Author Commit Data

**Time window**: Default window: "6 months ago". Use this same value for ALL git log invocations below.

```bash
git log --since="{since}" --format="AUTHOR:%aN DATE:%ai HASH:%H" --numstat -- . ':(exclude)vendor' ':(exclude)node_modules' ':(exclude).git' ':(exclude)var' ':(exclude)arch-docs'
```

Parse into per-author data: commit dates, files touched, lines added/deleted.

### 2. Build Author Profiles

For each contributor, compute:

#### Domain Expertise
- **Primary modules**: Top 3 modules by commit count
- **Module breadth**: Number of distinct modules touched
- **Exclusive modules**: Modules where this author is the sole contributor

#### Change Characteristics
- **Avg commit size**: Average lines added + deleted per commit
- **Commit frequency**: Commits per week
- **Change spread**: Average number of files per commit
- **Refactoring ratio**: Commits with negative net lines / total commits (higher = more refactoring)

#### Work Patterns
- **Active days**: Days of week with most commits
- **Consistency**: Standard deviation of weekly commit counts (low = steady, high = bursty)
- **Streak length**: Longest consecutive days with commits

#### Collaboration Signals
- **Co-author count**: Other developers whose files this author also modifies
- **Review proximity**: Files touched that overlap with other authors (good for review assignment)

### 3. Identify Expertise Domains

Map each author to their expertise domain using a weighted score:

```text
expertise(author, module) = commits × 0.4 + recent_commits × 0.3 + unique_files_touched × 0.3
```

Weight recent activity more heavily — someone who was active 6 months ago but hasn't contributed since has fading expertise.

### 4. Build Review Assignment Matrix

For each module, rank the best reviewers:
1. **Primary expert**: Most commits and recent activity
2. **Secondary expert**: Significant contributions, different perspective
3. **Learning reviewer**: Developer who should review for knowledge acquisition (low expertise, adjacent module knowledge)

### 5. Identify Patterns of Interest

- **Specialists**: Developers who concentrate on 1–2 modules (deep knowledge, bus factor risk)
- **Generalists**: Developers who touch many modules (broad knowledge, potential context-switching cost)
- **Fixers**: Developers with high fix-commit ratio (good at debugging, may indicate downstream issues)
- **Builders**: Developers with high new-code ratio (feature work)
- **Refiners**: Developers with high refactoring ratio (code quality focus)

## Output Format

### Developer Pattern Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Active contributors:** {count}

### Contributor Overview

| Author | Commits | Modules | Avg Size | Type | Primary Domain |
|--------|---------|---------|----------|------|---------------|
| @dev1 | 120 | 8 | 45 lines | Generalist/Builder | Order, Api |
| @dev2 | 95 | 3 | 82 lines | Specialist/Refiner | Billing |
| @dev3 | 60 | 5 | 28 lines | Generalist/Fixer | Auth, Email |

### Detailed Author Profiles

For each contributor:

---

#### @{author}

**Role classification:** {Specialist/Generalist} + {Builder/Fixer/Refiner}

| Metric | Value |
|--------|-------|
| **Total commits** | {count} |
| **Commits/week** | {avg} |
| **Avg commit size** | +{added}/−{deleted} lines |
| **Files per commit** | {avg} |
| **Module breadth** | {count} modules |
| **Refactoring ratio** | {percentage}% |
| **Fix-commit ratio** | {percentage}% |
| **Consistency** | {Steady / Bursty / Sporadic} |

**Domain expertise:**

| Module | Commits | Recency | Expertise Score | Role |
|--------|---------|---------|----------------|------|
| `src/Domain/Order/` | 45 | Active | 0.92 | Primary expert |
| `src/Infrastructure/Api/` | 30 | Active | 0.71 | Secondary expert |
| `src/Domain/Auth/` | 12 | 2mo ago | 0.35 | Familiar |

**Exclusive ownership** (sole contributor):
- `src/Utils/OrderCalculator.php` (bus factor = 1)
- `src/Legacy/ImportHelper.php` (bus factor = 1)

**Work pattern:**
```text
Mon: ████████ (18%)
Tue: ██████████ (22%)
Wed: █████████ (20%)
Thu: ████████ (18%)
Fri: ██████████ (22%)
```

**Collaboration overlap:**

| Co-developer | Shared Files | Shared Modules |
|-------------|-------------|----------------|
| @dev2 | 12 | Order, Api |
| @dev3 | 6 | Auth |

---

### Review Assignment Matrix

Best reviewer assignments by module:

| Module | Primary Reviewer | Secondary Reviewer | Learning Reviewer |
|--------|-----------------|-------------------|-------------------|
| `src/Domain/Order/` | @dev1 (0.92) | @dev2 (0.45) | @dev3 (0.15) |
| `src/Domain/Billing/` | @dev2 (0.88) | @dev1 (0.22) | @dev3 (0.10) |
| `src/Infrastructure/Api/` | @dev1 (0.71) | @dev2 (0.65) | @dev4 (0.08) |

### Pattern Distribution

| Pattern | Count | Authors |
|---------|-------|---------|
| Specialist | {count} | {list} |
| Generalist | {count} | {list} |
| Builder | {count} | {list} |
| Fixer | {count} | {list} |
| Refiner | {count} | {list} |

### Knowledge Gaps & Risks

| Risk | Details |
|------|---------|
| **Bus factor = 1 files** | {count} files solely owned by one developer |
| **Expertise silos** | {list of specialist developers and their exclusive modules} |
| **Fading expertise** | {authors whose recent activity has dropped significantly} |

### Knowledge Transfer Recommendations

| From | To | Module | Reason |
|------|-----|--------|--------|
| @dev1 | @dev3 | Order | Bus factor = 1 on 3 files; @dev3 has adjacent Auth knowledge |
| @dev2 | @dev1 | Billing | @dev2 is sole expert; @dev1 already touches Order which couples to Billing |

### Summary

| Metric | Value |
|--------|-------|
| Active contributors | {count} |
| Specialists (≤ 2 modules) | {count} |
| Generalists (≥ 5 modules) | {count} |
| Bus factor = 1 files | {count} |
| Modules with only 1 expert | {count} |


