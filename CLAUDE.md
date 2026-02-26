# Keywork — Agent Reference

Keywork is an autonomous coding platform that manages development of external repositories. It orchestrates plan-build-iterate cycles through goals (units of work), with each goal targeting a specific registered repo. Keywork separates agent code (this repo) from working repos (cloned into `workspace/`, changes committed back to those repos).

## Repo Layout

Agent system: `agents/` (prompts, skills, goals, repos, scripts, sandbox)
TUI & utilities: `keywork/` (Python package)
Working repos: `workspace/` (cloned repos, gitignored — never committed to keywork)
Tests: `tests/` (mirrors keywork/)

## How It Works

### Core Concepts

| Concept | Description |
|---------|-------------|
| Repo | A registered external repository that Keywork manages |
| Goal | A unit of work targeting one repo (like a project/ticket) |
| Skill | Task-type guidance loaded per-task by the build agent |
| Knowledge | Accumulated learnings about a repo's conventions and architecture |

### Agent Loop

1. Goals are the unit of work — each targets one registered repo
2. Plan agent reads PRD → creates IMPLEMENTATION.md (task checklist)
3. Build agent implements ONE task per run (code changes in the working repo)
4. Loop: build → check replan triggers → replan if needed → build again
5. Final gate validates all PRD requirements are met
6. Spec promotion commits specifications to working repo's `docs/specs/`

### Dual-Repo Operations

Build agents work across two git repos simultaneously:
- **Code changes** go to the working repo (`workspace/{repo}/`) — agent commits directly
- **State changes** (IMPLEMENTATION.md, journal) go to keywork — loop.sh commits after each run
- **Specs** are promoted to the working repo's `docs/specs/` on goal completion

### Context Layering

Build agents receive layered context in this priority order:
1. Keywork CLAUDE.md (this file) — agent system conventions
2. Working repo's CLAUDE.md — repo-specific conventions (if it exists)
3. Repo knowledge.md — accumulated learnings about the repo
4. Goal specs — task-specific requirements
5. Skill files — bundled + repo-specific task guidance

## Available Skills

Skills in `agents/skills/` provide task-specific guidance. The plan agent assigns skills to tasks via `[skill: name]` tags.

| Skill | When to use |
|-------|-------------|
| `testing` | Test creation and improvement |
| `docker` | Dockerfile and container patterns |
| `refactoring` | Code restructuring without behavior change |
| `api_development` | REST/GraphQL endpoint development |
| `documentation` | Writing docs, READMEs, guides |
| `ci_cd` | CI/CD pipeline creation and modification |

Repos can define additional skills in `agents/repos/{name}/skills/`.

## File Placement Rules

| New code type | Location |
|---------------|----------|
| Goal state files | `agents/goals/{goal-name}/` |
| Repo config | `agents/repos/{repo-name}/config.yaml` |
| Repo knowledge | `agents/repos/{repo-name}/knowledge.md` |
| Repo-specific skills | `agents/repos/{repo-name}/skills/` |
| Bundled skills | `agents/skills/` |
| Agent prompts | `agents/prompts/` |
| Promoted specs | `workspace/{repo}/docs/specs/` (in the working repo) |
| TUI code | `keywork/tui/` |
| Tests | `tests/` |

## Code Conventions

### Python (keywork/ package)

- Style enforced by **ruff**: `E`, `F`, `I`, `W` rules
- Line length: **120 characters**
- Naming: `snake_case` for everything (modules, functions, variables)
- Imports: sorted by ruff (isort-compatible)

### Shell Scripts

- Use `set -euo pipefail`
- Use functions for reusable logic
- Quote all variable expansions

## Anti-Patterns

- Do not put repo-specific conventions in Keywork's CLAUDE.md — put them in the repo's own CLAUDE.md or `agents/repos/{name}/knowledge.md`
- Do not store working repo state in Keywork — operational state (goals) is in Keywork, but specifications and code belong in the working repos
- Do not create monolithic skills — one skill per technology/pattern
- Do not skip the initialization interview — repos should always be profiled before work begins
- Do not hardcode check commands — lint, test, typecheck commands come from `agents/repos/{name}/config.yaml`

## Agent Environment

Agents execute inside Docker sandbox containers with:
- `/workspace` mounted from `workspace/{repo}` (read-write, for code)
- `/state` mounted from `agents/goals/{goal}` (read-write, for state)
- `/agents` mounted from `agents/` (read-only, for prompts/skills)
- Claude CLI authenticated via host credential forwarding
- SSH agent forwarded for git operations

Credential errors are bugs, not limitations. If you encounter a credential error, investigate and fix it.
