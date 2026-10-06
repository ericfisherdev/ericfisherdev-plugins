# Create Overview Command

## Contents

- Analysis Requirements
- Output Format

Act as a senior software architect tasked with understanding this new project. Analyze the entire workspace thoroughly.

## Analysis Requirements

Provide a concise summary covering ALL of the following sections in order:

### 1. Project Purpose

- What problem does this project seem to solve?
- What is its primary domain?

### 2. Architecture Pattern

- The overall architectural pattern or patterns used

### 3. Technology Stack

Identify the primary programming languages, frameworks, and any major libraries or dependencies suggested by the configuration/package files.

**For Python projects specifically**: Examine `requirements.txt`, `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, and `poetry.lock` files to identify all Python dependencies, their versions, and purposes.

> [!note]
> When looking for dependencies, package names, or library names, perform **case-insensitive matching** and consider variations with dashes between words (e.g., "new-relic", "data-dog", "express-rate-limit").

### 4. Initial Structure Impression

Based on the root directory structure, what seem to be the main high-level parts of this application? Examples:
- Frontend
- Backend
- Workers
- Libraries
- Services

### 5. Configuration/Package Files

Identify and list ALL configuration or package files found in the project, including but not limited to:
- `package.json`, `package-lock.json`, `yarn.lock`
- `composer.json`, `composer.lock`
- `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`
- `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`
- `.env`, `.env.example`
- `Dockerfile`, `docker-compose.yml`
- `Makefile`, `CMakeLists.txt`
- Config files (`.eslintrc`, `tsconfig.json`, `webpack.config.js`, etc.)

### 6. Directory Structure

Describe the purpose of all the source code directories and how the code appears to be organized:
- Is it organized by feature?
- Is it organized by layer?
- Is it a hybrid approach?

Provide a brief description of each major directory's purpose.

### 7. High-Level Architecture

What architectural pattern(s) seem to be employed? Examples:
- Layered Architecture
- MVC (Model-View-Controller)
- Microservices
- Event-Driven
- Hexagonal/Clean Architecture
- Domain-Driven Design

**Provide evidence** supporting your assessment:
- Specific directories
- Framework usage
- Communication patterns
- Configuration files

### 8. Build, Execution and Test

How is the project typically built, run, and tested based on the available scripts and configuration files?

- List build commands
- List run/start commands
- List test commands
- Identify the main entry point(s) if possible

## Output Format

Format your entire output clearly using markdown with:
- Clear section headers (use `##` for main sections)
- Bullet points for lists
- Code blocks for file names and commands
- Tables where appropriate for dependencies or configuration files
