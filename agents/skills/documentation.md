# Skill: Documentation

## When to Use

Use this skill when the task is creating or updating documentation: READMEs, API docs, architecture overviews, deployment guides, configuration references, or inline code documentation. Also use this skill when code changes require corresponding documentation updates.

## Core Principle

Documentation is a deliverable with the same quality bar as code. Broken documentation — wrong commands, deprecated URLs, incorrect table names, outdated screenshots — is equivalent to broken code. Fix documentation bugs with the same rigor as code bugs.

## README Structure

Every project README should follow this structure (omit sections that do not apply):

```markdown
# Project Name

Brief description of what this project does and who it is for (1-2 sentences).

## Quick Start

Minimal steps to get the project running:

    git clone <repo-url>
    cd <project>
    <install-command>
    <run-command>

## Prerequisites

- Language runtime and version
- Required system tools
- External service accounts or API keys

## Installation

Step-by-step installation with copy-pasteable commands.

## Usage

Common usage patterns with examples.

## Configuration

Environment variables and config files with descriptions and defaults.

| Variable | Description | Default | Required |
|----------|------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | — | Yes |
| `LOG_LEVEL` | Logging verbosity | `info` | No |

## Development

How to set up a development environment, run tests, lint, and build.

## Deployment

How to deploy to each environment.

## Architecture

High-level overview for contributors (or link to separate architecture doc).

## Contributing

Contribution guidelines, PR process, code style expectations.
```

## Writing Style

- **Concise and task-oriented**: Write for someone who wants to accomplish something, not someone who wants to read a textbook.
- **Use code blocks for commands**: Every command must be in a fenced code block with the appropriate language tag.
- **Use tables for reference data**: Configuration options, environment variables, API endpoints — tables are scannable.
- **Use headings for navigation**: Readers skim headings. Make each heading describe the content below it.
- **Active voice**: "Run the migration" not "The migration should be run."
- **Present tense**: "This function returns" not "This function will return."

## Copy-Pasteable Commands

Every command in documentation must be copy-pasteable and correct:

```bash
# Good — complete, specific, works when pasted
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000

# Bad — vague, incomplete, won't work
install dependencies
run the server
```

Test commands before including them. If a command requires substitution, use angle brackets and explain:

```bash
export DATABASE_URL=<your-connection-string>
```

## API Documentation

For each endpoint, document:

1. **Method and path**: `POST /api/v1/users`
2. **Description**: What it does in one sentence
3. **Request**: Headers, parameters, body schema with types
4. **Response**: Status codes, body schema, example
5. **Errors**: Possible error codes and their meanings

Use tables for request body schemas (field, type, required, description) and error codes (status, code, description). Include a concrete response example as a JSON code block.

## Architecture Documentation

For system and architecture docs:

- **Start with context**: What problem does this system solve? Who uses it?
- **Component overview**: List the major components and their responsibilities
- **Use ASCII diagrams**: They live in the code, diff cleanly, and never go stale if maintained

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  Client   │────▶│   API    │────▶│ Database │
│  (React)  │◀────│ (FastAPI)│◀────│ (Postgres)│
└──────────┘     └──────────┘     └──────────┘
                       │
                       ▼
                 ┌──────────┐
                 │  Queue   │
                 │ (Redis)  │
                 └──────────┘
```

- **Data flow**: Describe how data moves through the system
- **Key decisions**: Document architectural decisions with rationale — why this database, why this queue, why this deployment model
- **Keep it current**: When architecture changes, update the docs in the same commit

## Deployment Guides

Deployment documentation must be:

1. **Step-by-step**: Numbered steps in exact order
2. **Environment-specific**: Separate sections for staging vs. production if they differ
3. **Idempotent**: Running the same steps twice should not break anything
4. **Reversible**: Include rollback steps for each deployment

Every step should be a numbered item with the exact command in a code block. Include a rollback section with the exact commands to undo the deployment.

## Keeping Docs in Sync

When code changes, check if documentation needs updating:

- **New feature** — does the README mention it? Are there usage examples?
- **Changed API** — are request/response schemas updated?
- **Changed config** — are environment variable tables updated?
- **Changed commands** — are install/build/deploy steps still correct?
- **Removed feature** — is all mention of it removed from docs?

If you change behavior and do not update docs, the documentation is now a bug.

## Inline Code Documentation

- **Functions**: Describe what it does, parameters, return value, and exceptions — but only when the function name and signature are not self-explanatory
- **Complex logic**: Add a brief comment explaining why, not what — the code says what, comments say why
- **Do not**: Comment obvious code (`i += 1  // increment i`), leave outdated comments, write novels in docstrings

## Anti-Patterns

- **Documentation that duplicates code**: If the code is clear, do not restate it in a comment. Document intent, not mechanics.
- **Aspirational docs**: Do not document features that do not exist yet. Document what is.
- **Stale screenshots**: Screenshots rot faster than text. Use them sparingly and update them when the UI changes.
- **Wall of text**: Use headings, lists, tables, and code blocks to make docs scannable.
- **Undocumented prerequisites**: If a tool must be installed first, say so explicitly with version requirements.
- **Broken links**: Verify that all links point to valid targets. Relative links are preferred over absolute URLs within the same repo.

## Checklist Before Submitting

1. All commands are copy-pasteable and tested
2. All URLs, paths, and identifiers match the actual codebase
3. Configuration tables include all current variables with correct defaults
4. Code examples are syntactically correct and runnable
5. No references to removed features or deprecated interfaces
6. Headings provide clear navigation for the document
7. Writing is concise, task-oriented, and in active voice
