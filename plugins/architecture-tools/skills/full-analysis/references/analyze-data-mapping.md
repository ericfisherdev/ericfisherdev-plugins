# Analyze Data Mapping Command

## Contents

- Data Mapping Analysis Requirements
- Output Format

You are a data privacy and compliance specialist. Analyze this codebase to map all personal data flows and assess data protection mechanisms.

> [!important] Special Instruction
> Focus ONLY on identifying data flows, processing mechanisms, and privacy controls that are ACTUALLY present in the code. Do NOT list compliance requirements or tools that are not implemented.
> [!important] Special Instruction
> Ignore any files under `arch-docs` folder.

## Data Mapping Analysis Requirements

### 1. Data Collection Points

Identify where data enters the system:

#### User Input Forms
- Registration forms
- Profile update forms
- Contact forms
- Survey/feedback forms

#### API Endpoints
- Data submission endpoints
- File upload endpoints
- Third-party data ingestion

#### Automated Collection
- Cookies and tracking
- Analytics data
- System logs with user data
- Device/browser information

### 2. Data Categories

Classify data found in the codebase:

#### Personal Identifiers
- Names, emails, phone numbers
- User IDs, account numbers
- IP addresses, device IDs
- Social security numbers

#### Sensitive Personal Data
- Financial information (credit cards, bank accounts)
- Health/medical data
- Biometric data
- Racial/ethnic origin
- Political/religious beliefs
- Sexual orientation

#### Authentication Credentials
- Passwords (storage method)
- API keys, tokens
- Security questions

#### Behavioral Data
- Usage patterns
- Preferences
- Location data
- Browsing history

### 3. Data Processing Operations

Document how data is processed:

#### Validation & Transformation
- Input validation rules
- Data normalization
- Format conversions

#### Storage
- Database storage (encrypted/plaintext)
- File storage
- Cache storage
- Session storage

#### Transmission
- API calls with personal data
- Email/SMS with user data
- Third-party integrations

### 4. Third-Party Data Sharing

Identify external data transfers:

| Third Party | Data Shared | Purpose | Legal Basis |
|-------------|-------------|---------|-------------|
| Stripe | Payment info | Payment processing | Contract |
| SendGrid | Email, name | Email delivery | Consent |
| Analytics | User behavior | Analytics | Legitimate interest |

### 5. Data Subject Rights Implementation

Check for implementations of:

- **Right to Access**: Data export functionality
- **Right to Rectification**: Data update mechanisms
- **Right to Erasure**: Account/data deletion
- **Right to Portability**: Data export formats
- **Right to Restrict Processing**: Opt-out mechanisms
- **Right to Object**: Preference management

### 6. Data Protection Mechanisms

Document security controls:

#### Encryption
- At-rest encryption (database, files)
- In-transit encryption (TLS/SSL)
- Field-level encryption

#### Access Controls
- Who can access personal data
- Audit logging of data access
- Data masking/anonymization

#### Data Minimization
- Only collecting necessary data
- Retention policies implemented
- Automatic data purging

### 7. Compliance Indicators

Look for implementations related to:

- **GDPR**: EU data protection
- **CCPA**: California privacy
- **HIPAA**: Health data (if applicable)
- **PCI DSS**: Payment card data
- **SOC 2**: Security controls

## Output Format

### Data Flow Diagram

```
[User Input] → [Validation] → [Processing] → [Storage]
                                    ↓
                           [Third-Party APIs]
```

### Personal Data Inventory

| Data Element | Category | Collection Point | Storage | Retention | Encryption |
|--------------|----------|------------------|---------|-----------|------------|
| Email | PII | Registration | DB | Indefinite | No |
| Password | Credential | Registration | DB | Indefinite | Hashed |
| Credit Card | Sensitive | Checkout | Stripe | Not stored | N/A |

### Data Flow Documentation

For each significant data flow:

#### Flow: [Name]
- **Source**: Where data originates
- **Processing**: What happens to the data
- **Destination**: Where data ends up
- **Personal Data Involved**: [list fields]
- **Legal Basis**: [if identifiable]

### Privacy Risk Assessment

| Risk | Severity | Location | Recommendation |
|------|----------|----------|----------------|
| Unencrypted PII storage | HIGH | `users` table | Implement encryption |
| Missing data deletion | MEDIUM | User service | Add deletion endpoint |

### Summary

- **Personal Data Types Found**: [count]
- **Third-Party Integrations**: [count]
- **Data Subject Rights Implemented**: [list]
- **Key Compliance Gaps**: [list]


