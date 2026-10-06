# Analyze Authentication Command

## Contents

- Authentication Analysis Requirements
- Output Format
- Security Vulnerabilities Found
- Summary

You are a security architect specializing in authentication. Analyze all authentication mechanisms, identity management, and access control systems in this codebase.

> [!important] Special Instruction
> If no authentication mechanisms are found, return `no authentication mechanisms detected`. Only document authentication systems that are ACTUALLY implemented in the codebase. Do NOT list authentication methods, frameworks, or tools that are not present.

> [!important] Special Instruction
> Ignore any files under `arch-docs` folder.

## Authentication Analysis Requirements

### 1. Primary Authentication Methods

Identify implementations of:
- **JWT (JSON Web Tokens)**: Token generation, validation, refresh mechanisms
- **OAuth 2.0 / OpenID Connect**: Authorization flows, token handling
- **SAML**: SSO implementations
- **Basic Authentication**: Username/password over HTTP
- **API Keys**: Key generation, validation, rotation
- **Session-based**: Cookie-based session management
- **Multi-factor Authentication (MFA)**: TOTP, SMS, email verification

### 2. Identity Management

Document:
- **Local Authentication**: Username/password storage and validation
- **Social Login Integrations**: Google, Facebook, GitHub, Apple, etc.
- **Enterprise SSO**: LDAP, Active Directory, Okta integration
- **Third-party Identity Services**: Auth0, Firebase Auth, AWS Cognito, Keycloak

### 3. Credential Handling

Analyze:
- **Password Storage**: Hashing algorithms (bcrypt, scrypt, Argon2)
- **Salt Generation**: Random salt implementation
- **Password Policies**: Complexity requirements, expiration
- **Credential Validation**: Input validation and sanitization

### 4. Token Management

Document:
- **Token Creation**: Signing algorithms, payload structure
- **Token Storage**: Client-side (localStorage, cookies) and server-side
- **Token Expiration**: Access token and refresh token lifetimes
- **Token Rotation**: Refresh token rotation strategy
- **Token Revocation**: Blacklisting, logout mechanisms

### 5. Session Architecture

Analyze:
- **Session Storage**: In-memory, Redis, database
- **Session Lifecycle**: Creation, validation, destruction
- **Session Timeout**: Idle timeout, absolute timeout
- **Session ID Generation**: Randomness, entropy
- **Session Fixation Prevention**: ID regeneration on login

### 6. Authentication Flows

Document each flow:
- **Login Process**: Steps, validation, response handling
- **Logout Process**: Token/session invalidation, cleanup
- **Registration**: Account creation, email verification
- **Password Recovery**: Reset flow, token expiration
- **Account Lockout**: Failed attempt handling, unlock mechanisms

### 7. Security Headers & Cookies

Check for:
- **CORS Configuration**: Allowed origins, credentials
- **CSP (Content Security Policy)**: Script sources, frame ancestors
- **X-Frame-Options**: Clickjacking protection
- **HSTS**: Strict transport security
- **Cookie Attributes**: HttpOnly, Secure, SameSite

### 8. API & Service Authentication

Document:
- **API Key Management**: Generation, storage, validation
- **Service-to-Service Auth**: Internal service authentication
- **mTLS Implementation**: Certificate-based authentication
- **Bearer Token Handling**: Header parsing, validation

## Output Format

For each authentication mechanism found:

---

### Authentication Method: [Name]

**Type:** [JWT / OAuth / Session / API Key / etc.]

**Location:**
- Files: `path/to/file.ext`
- Functions/Classes: [list relevant code]

**Implementation Details:**
```[language]
// Key code snippets showing implementation
```

**Configuration:**
- Token expiration: [duration]
- Algorithm: [if applicable]
- Storage: [where credentials/tokens stored]

**Security Assessment:**
- Strengths: [list positive aspects]
- Weaknesses: [list concerns]

---

## Security Vulnerabilities Found

List any authentication-related security issues:

| Issue | Severity | Location | Description |
|-------|----------|----------|-------------|
| [Issue] | CRITICAL/HIGH/MEDIUM/LOW | `file:line` | [Description] |

## Summary

- **Total Authentication Methods:** [count]
- **Primary Method:** [main authentication approach]
- **Identity Providers:** [list external providers]
- **Overall Security Posture:** [assessment]


