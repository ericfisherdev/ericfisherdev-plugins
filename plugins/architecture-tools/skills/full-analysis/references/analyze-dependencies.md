# Analyze Dependencies Command

## Contents

- Definition of an External Dependency
- Clues to Look For
- Output Format
- Analysis Instructions
- Summary Section
- Risk Assessment

You are an expert software architect and code analyzer. Your task is to analyze the codebase and identify all its external dependencies.

## Definition of an External Dependency

An "external dependency" in this context refers to any service (internal or external), library, or resource that is not part of the codebase itself but is required for the codebase to function correctly during runtime. These dependencies typically reside outside the immediate project's source code and are often managed via package managers, API calls, or configuration.

## Clues to Look For

### 1. API Calls
Outgoing HTTP/S requests to external services (e.g., `fetch`, `axios`, `requests` library calls to third-party APIs like payment gateways, mapping services, social media APIs).

### 2. Event Broker Interactions
Publishing to or consuming from external message queues or event streams:
- AWS SQS
- Azure Event Hubs
- Kafka
- Ably
- RabbitMQ

### 3. Database Connections
Connections to databases that are hosted externally or managed as separate services:
- AWS RDS
- MongoDB Atlas
- Redis Cloud
- PostgreSQL
- MySQL

### 4. Cloud Service SDKs
Usage of SDKs for cloud providers to interact with their services:
- AWS SDK (S3, Lambda, DynamoDB, etc.)
- Azure SDK (Blob Storage, Functions, etc.)
- Google Cloud SDK (GCS, Cloud Functions, etc.)

### 5. Package Manager Definitions
Entries in configuration files that list required libraries or modules:
- `package.json` for npm/yarn
- `requirements.txt` for pip
- `pyproject.toml` for Python
- `pom.xml` for Maven
- `build.gradle` for Gradle
- `Gemfile` for Bundler
- `go.mod` for Go modules
- `composer.json` for PHP
- `Cargo.toml` for Rust

**For Python projects specifically**: Thoroughly examine `requirements.txt`, `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, `poetry.lock`, and any other Python dependency files to identify all external Python packages, their versions, and their purposes in the project.

> [!note]
> When looking for dependencies, package names, or library names, perform **case-insensitive matching** and consider variations with dashes between words (e.g., "new-relic", "data-dog", "express-rate-limit").

### 6. Configuration Files
Environment variables, `.env` files, or dedicated configuration files that store:
- URLs
- API keys
- Connection strings
- Service endpoints pointing to external resources

### 7. External File Storage
Interactions with external file storage services:
- S3 buckets
- Google Cloud Storage
- Azure Blob Storage
- MinIO

### 8. Authentication/Authorization Services
Integration with external identity providers:
- Auth0
- Okta
- OAuth providers (Google, Facebook, GitHub login)
- Keycloak
- AWS Cognito

### 9. Monitoring/Logging Tools
Integrations with external monitoring, logging, or analytics platforms:
- Datadog
- New Relic
- Splunk
- Google Analytics
- Sentry
- PagerDuty

### 10. Container Images/Orchestration
References to base images or external services in:
- Dockerfiles
- Kubernetes manifests
- docker-compose.yml
- Helm charts

## Output Format

For each external dependency identified, provide the following information:

---

### [Dependency Name]

| Attribute | Details |
|-----------|---------|
| **Type** | [Third-party API / Message Broker / External Service / Internal Service / Library/Framework / Database / Authentication Service / Monitoring Tool / Cloud Service / File Storage] |
| **Purpose/Role** | [Concise explanation of why this dependency is used and its primary function] |
| **Integration Points** | [Specific files, configuration entries, or code patterns indicating usage] |

**Evidence:**
```
[Relevant code snippet or configuration showing the integration]
```

---

## Analysis Instructions

### Thorough Scan
Examine all relevant files, including:
- Source code files
- Configuration files
- Build scripts
- Dependency manifests

> [!important]
> When reading dependency files like `package.json`, DO NOT read files partially. ALWAYS read them fully.

### Distinguish Internal vs. External
Focus strictly on components outside the codebase itself. Internal modules or services within the same repository are NOT external dependencies for this analysis.

### Infer Usage
If explicit documentation is lacking, infer the dependency's purpose and integration points based on code logic and configuration. **MENTION** that it is an **ASSUMPTION** and requires further investigation.

### Clarity and Detail
Provide clear, concise descriptions, but include enough detail to understand the dependency's nature and its interaction with the codebase.

> [!important] Special Instruction
> Ignore any files under `arch-docs` folder.

## Summary Section

After listing all dependencies, provide a summary table:

| Category | Count | Dependencies |
|----------|-------|--------------|
| Third-party APIs | X | [list] |
| Databases | X | [list] |
| Cloud Services | X | [list] |
| Libraries/Frameworks | X | [list] |
| Message Brokers | X | [list] |
| Auth Services | X | [list] |
| Monitoring Tools | X | [list] |
| Other | X | [list] |

## Risk Assessment

For critical external dependencies, note:
- **Single points of failure**: Dependencies without fallbacks
- **Version risks**: Outdated or deprecated dependencies
- **Security considerations**: Dependencies handling sensitive data


