# Analyze Authorization Command

## Contents

- Authorization Analysis Requirements
- Output Format
- Security Vulnerabilities Found
- Summary

You are a security architect specializing in authorization. Analyze all authorization mechanisms, access control, and permission systems in this codebase.

> [!important] Special Instruction
> If no authorization mechanisms are found, return `no authorization mechanisms detected`. Only document authorization systems that are ACTUALLY implemented in the codebase. Do NOT list authorization methods, frameworks, or tools that are not present.

> [!important] Special Instruction
> Ignore any files under `arch-docs` folder.

## Authorization Analysis Requirements

### 1. Access Control Models

Identify implementations of:
- **Role-Based Access Control (RBAC)**: Role definitions, assignments
- **Attribute-Based Access Control (ABAC)**: Attribute evaluation, policies
- **Policy-Based Access Control (PBAC)**: Policy definitions, enforcement
- **Access Control Lists (ACL)**: Resource-level permissions
- **Capability-based Security**: Token/capability handling

### 2. Permission Structure

Document:
- **Permission Definitions**: What permissions exist
- **Permission Hierarchies**: Parent/child relationships
- **Permission Inheritance**: How permissions cascade
- **Dynamic Permissions**: Runtime permission evaluation
- **Resource-based Permissions**: Per-resource access control

### 3. Roles & Groups

#### Role Management
- Role definitions and naming
- Role hierarchies
- Default roles vs custom roles
- System roles (admin, user, guest)

#### Group Management
- Group structures and memberships
- Group-level permissions
- Nested groups

#### User-Role Mapping
- Assignment mechanisms
- Multiple roles per user
- Role activation/deactivation

### 4. Permission Checking

#### Authorization Middleware/Guards
- Route-level permission checks
- Method-level authorization
- Field-level access control
- Resource ownership validation

#### Authorization Logic
- Permission evaluation order
- Decision points in code
- Override capabilities
- Fallback permissions

### 5. Resource Access Control

Document:
- **CRUD Permissions**: Create, Read, Update, Delete per resource
- **Custom Actions**: Non-CRUD permission checks
- **Ownership Models**: Creator permissions, shared ownership
- **Public vs Private**: Resource visibility rules

### 6. Policy Engine

If present:
- **Policy Definition**: Language/DSL used
- **Policy Storage**: Files, database, external service
- **Policy Evaluation**: How policies are checked
- **Policy Conflicts**: Resolution strategy

### 7. Database Schema

Document authorization-related tables:
- Roles table structure
- Permissions table structure
- User-role mappings
- Role-permission mappings
- Resource permissions

### 8. API Authorization

Document:
- **Endpoint Protection**: Required permissions per endpoint
- **HTTP Method Restrictions**: GET vs POST vs DELETE permissions
- **OAuth Scopes**: Scope definitions and requirements
- **Rate Limiting by Role**: Different limits per permission level

### 9. Frontend Authorization

Document:
- **Component Visibility**: Conditional rendering based on permissions
- **Route Guards**: Protected routes, redirects
- **Feature Flags**: Permission-based feature access
- **UI Element Control**: Button/menu enabling/disabling

### 10. Multi-Tenancy

If applicable:
- **Tenant Isolation**: Data segregation approach
- **Cross-tenant Restrictions**: What's blocked
- **Tenant Admin Roles**: Tenant-specific administration
- **Super Admin Access**: Cross-tenant capabilities

## Output Format

For each authorization mechanism found:

---

### Authorization System: [Name/Type]

**Model:** [RBAC / ABAC / ACL / Custom]

**Location:**
- Files: `path/to/file.ext`
- Functions/Classes: [list relevant code]

**Roles Defined:**
| Role | Permissions | Description |
|------|-------------|-------------|
| admin | * | Full access |
| user | read, write | Standard user |

**Permission Checks:**
```[language]
// Code showing how permissions are checked
```

**Database Schema:**
```sql
-- Relevant table structures
```

---

## Security Vulnerabilities Found

| Issue | Severity | Location | Description |
|-------|----------|----------|-------------|
| Missing auth check | HIGH | `file:line` | [Description] |
| IDOR vulnerability | CRITICAL | `file:line` | [Description] |

## Summary

- **Access Control Model:** [RBAC/ABAC/etc.]
- **Total Roles:** [count]
- **Total Permissions:** [count]
- **Multi-tenant:** [Yes/No]
- **Security Assessment:** [brief assessment]


