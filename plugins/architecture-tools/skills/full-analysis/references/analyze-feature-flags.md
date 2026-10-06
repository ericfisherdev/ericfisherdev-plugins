# Analyze Feature Flags Command

## Contents

- Feature Flag Analysis Requirements
- Output Format

You are a software architect expert in feature flag systems and CI/CD. Analyze all feature flag implementations and usage in this codebase.

> [!important] Special Instruction
> If no feature flag systems are found, return `no feature flag usage detected`. Only document feature flag systems that are ACTUALLY implemented in the codebase. Do NOT list feature flag platforms or tools that are not present.
> [!important] Special Instruction
> Ignore any files under `arch-docs` folder.

## Feature Flag Analysis Requirements

### 1. Feature Flag Framework Detection

Identify feature flag platforms or libraries:

#### Commercial Platforms
- **LaunchDarkly**: `launchdarkly-*` packages
- **Split.io**: `@splitsoftware/*` packages
- **Optimizely**: Optimizely SDK
- **ConfigCat**: `configcat-*` packages
- **Flagsmith**: `flagsmith-*` packages
- **Unleash**: `unleash-*` packages

#### Open Source / Self-Hosted
- **Unleash** (self-hosted)
- **Flagr**
- **Flipt**
- **Feature flags in config files**

#### Custom Implementations
- Environment variables as flags
- Database-stored flags
- Config file flags
- Custom flag services

### 2. Framework Configuration

Document the feature flag setup:

---

### Platform: [Name]

**SDK/Library:** [package name and version]

**Initialization:**
```[language]
// Code showing client initialization
```

**Configuration:**
| Setting | Value | Location |
|---------|-------|----------|
| API Key | `env.LAUNCHDARKLY_KEY` | Environment |
| Streaming | Enabled | Config |
| Offline Mode | Disabled | Config |

**Environment Differences:**
| Environment | Configuration |
|-------------|---------------|
| Development | Local overrides |
| Staging | Full SDK |
| Production | Full SDK |

---

### 3. Feature Flag Inventory

For each flag found, document:

---

### Flag: `flag_name`

**Type:** [Boolean / String / Number / JSON]

**Purpose:** [What this flag controls]

**Default Value:** [Default state when flag is not found]

**Current Evaluations:**

| Location | File | Lines | Usage Pattern |
|----------|------|-------|---------------|
| Feature gate | `src/components/NewFeature.tsx` | 15-20 | Conditional render |
| API route | `src/api/users.ts` | 45 | Response variation |

**Targeting (if known):**
- User segments targeted
- Percentage rollout
- Environment-specific values

**Impact Analysis:**
- What happens when flag is ON
- What happens when flag is OFF
- Components/features affected

**Code Example:**
```[language]
// Actual code showing flag evaluation
```

---

### 4. Flag Categories

Group flags by purpose:

#### Release Flags
Flags used for gradual rollouts of new features:

| Flag | Feature | Rollout Status |
|------|---------|----------------|
| `new_checkout_flow` | Redesigned checkout | 50% |
| `v2_api_enabled` | API v2 endpoints | Beta users |

#### Experiment Flags
Flags used for A/B testing:

| Flag | Experiment | Variants |
|------|------------|----------|
| `homepage_hero_variant` | Hero design test | A, B, C |
| `pricing_page_layout` | Pricing layout test | control, treatment |

#### Operational Flags (Kill Switches)
Flags for emergency disabling:

| Flag | Purpose | Default |
|------|---------|---------|
| `enable_third_party_api` | External API circuit breaker | true |
| `maintenance_mode` | Site-wide maintenance | false |

#### Permission Flags
Flags controlling feature access:

| Flag | Controls Access To |
|------|-------------------|
| `beta_features_enabled` | Beta program features |
| `premium_analytics` | Paid analytics dashboard |

### 5. Flag Usage Patterns

Document common patterns:

#### Simple Boolean Check
```[language]
if (flagClient.isEnabled('feature_x')) {
  // New behavior
}
```

#### Variation/String Flags
```[language]
const variant = flagClient.getVariation('experiment_y', 'control');
```

#### User Targeting
```[language]
const isEnabled = flagClient.isEnabledForUser('feature_z', user);
```

### 6. Context & Targeting

Document what context is used for flag evaluation:

| Context Attribute | Source | Used For |
|-------------------|--------|----------|
| userId | Auth token | User targeting |
| email | User profile | Beta access |
| plan | Subscription | Feature gates |
| country | GeoIP | Regional rollouts |

### 7. Flag Lifecycle

Identify flags that may need attention:

#### Potentially Stale Flags
| Flag | Last Modified | Status |
|------|---------------|--------|
| `old_feature_flag` | 6 months ago | Always ON |

#### Fully Rolled Out
| Flag | Recommendation |
|------|----------------|
| `feature_100_percent` | Remove flag, keep feature |

### 8. Testing Considerations

Document:
- How flags are mocked in tests
- Test coverage for flag variations
- Integration testing with flag service

## Output Format

### Feature Flag Overview

| Platform | SDK | Flags Found | Configuration |
|----------|-----|-------------|---------------|
| LaunchDarkly | `launchdarkly-node-server-sdk` | 15 | `src/config/flags.ts` |

### Flag Inventory

[Complete list of all flags with their details]

### Flag Categories Summary

| Category | Count | Examples |
|----------|-------|----------|
| Release | 5 | `new_checkout`, `v2_api` |
| Experiment | 3 | `hero_variant`, `pricing_test` |
| Kill Switch | 4 | `enable_payments`, `maintenance` |
| Permission | 3 | `beta_access`, `premium_features` |

### Recommendations

| Recommendation | Flags Affected | Priority |
|----------------|----------------|----------|
| Remove stale flags | `old_feature_x` | Medium |
| Clean up 100% rollouts | `feature_y` | Low |

### Summary

- **Platform:** [name]
- **Total Flags:** [count]
- **Active Experiments:** [count]
- **Kill Switches:** [count]
- **Potentially Stale:** [count]


