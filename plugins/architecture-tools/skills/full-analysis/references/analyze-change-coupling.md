# Analyze Change Coupling Command

## Contents

- Analysis Steps
- Output Format

You are an expert in behavioral code analysis (per Adam Tornhill's "Software Design X-Rays"). Your task is to identify **change coupling** — files that consistently change together in the same commits — because this reveals hidden temporal dependencies that may not be visible in the import/dependency graph.

> [!important] Special Instruction
> Ignore any files under `arch-docs`, `vendor`, `node_modules`, `.git`, and `var` folders.

## Analysis Steps

### 1. Extract Co-Change Data

**Time window**: Default window: `"6 months ago"`. Use this same value for ALL git log invocations below.

Get all commits with the files they changed:

```bash
git log --since="{since}" --format="COMMIT:%H" --name-only
```

Parse this into a mapping of `commit → [files]`.

### 2. Build Co-Change Matrix

For every pair of files that appeared in the same commit, count how many times they changed together.

**Minimum threshold**: A pair must co-change at least 3 times (configurable via `--min-coupling`) to be considered coupled.

### 3. Calculate Coupling Strength

For each file pair (A, B):

```
coupling_strength = co_changes(A, B) / max(changes(A), changes(B))
```

A coupling strength of 1.0 means the files ALWAYS change together. Values above 0.5 are notable.

### 4. Classify Coupling Type

For each coupled pair, determine if the coupling is:

- **Structural** — Files import/reference each other (expected coupling)
- **Temporal-only** — Files do NOT import each other but still co-change (hidden dependency — this is the interesting finding)
- **Cross-boundary** — Files are in different modules/domains (potential architecture violation)

To check structural coupling, look for:
- `import`/`require`/`use` statements between the files
- Class/function references
- Shared configuration references

### 5. Identify Coupling Clusters

Group files that form a connected graph of coupling into clusters. A cluster of 4+ files that always change together may indicate:
- A feature that should be a single module
- A "god object" whose changes ripple across the codebase
- A missing abstraction

## Output Format

### Change Coupling Analysis

**Repository:** {repo name}
**Period:** {start date} to {current date}
**Commits analyzed:** {count}
**Minimum coupling threshold:** {count} co-changes

### Top Coupled File Pairs

| Rank | File A | File B | Co-Changes | Strength | Type |
|------|--------|--------|------------|----------|------|
| 1 | `src/Order/Order.php` | `src/Order/OrderRepository.php` | 23 | 0.85 | Structural |
| 2 | `src/User/UserService.php` | `src/Email/EmailService.php` | 15 | 0.71 | Cross-boundary ⚠️ |
| 3 | `src/Api/AuthController.php` | `src/Domain/Session/Session.php` | 12 | 0.67 | Temporal-only ⚠️ |

### Hidden Dependencies (Temporal-Only Coupling)

These file pairs change together frequently but have NO direct import/reference relationship. This is the most actionable finding.

---

#### `file_a` ↔ `file_b`

| Metric | Value |
|--------|-------|
| **Co-changes** | {count} |
| **Coupling strength** | {value} |
| **File A changes (total)** | {count} |
| **File B changes (total)** | {count} |
| **Modules** | {module_a} ↔ {module_b} |

**Possible explanation:** {hypothesis — e.g., "Both files depend on a shared database schema", "Changes to the API contract require updates in both"}

**Recommendation:** {e.g., "Introduce a shared interface", "Consider merging into a single module", "Add an integration test to catch drift"}

---

### Cross-Boundary Coupling

File pairs in different domains/modules that change together — potential violations of module boundaries:

| File A (Module) | File B (Module) | Co-Changes | Strength |
|----------------|----------------|------------|----------|
| `src/Order/...` | `src/Billing/...` | 18 | 0.72 |

### Coupling Clusters

Groups of 3+ files that form a tightly coupled change cluster:

---

#### Cluster: {descriptive name}

**Files:**
- `path/to/file1`
- `path/to/file2`
- `path/to/file3`
- `path/to/file4`

**Internal coupling strength:** {average strength within cluster}
**Total co-changes:** {count}
**Assessment:** {e.g., "These files represent a single logical unit that should be co-located", "This cluster suggests a missing abstraction layer"}

---

### Coupling vs. Architecture Comparison

| Module Boundary | Expected Coupling | Actual Coupling | Assessment |
|----------------|-------------------|-----------------|------------|
| Order ↔ Order | High | High | ✅ Aligned |
| Order ↔ Billing | Low | High | ⚠️ Misaligned |
| User ↔ Auth | Medium | Medium | ✅ Aligned |

### Summary

| Metric | Value |
|--------|-------|
| File pairs analyzed | {count} |
| Coupled pairs (above threshold) | {count} |
| Hidden (temporal-only) dependencies | {count} |
| Cross-boundary couplings | {count} |
| Coupling clusters | {count} |

### Recommendations

1. **Highest priority**: {most concerning hidden dependency}
2. **Architecture concern**: {most concerning cross-boundary coupling}
3. **Cluster action**: {recommendation for largest cluster}


