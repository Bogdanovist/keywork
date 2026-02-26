# Keywork — Human Developer Guide

## What is Keywork?

Keywork is an autonomous coding platform that manages development of external repositories through agent-driven plan-build-iterate cycles. It separates the autonomous development system from the code it builds — Keywork orchestrates, working repos receive the commits.

In The Amory Wars universe, the Keywork is the energy lattice that binds the worlds together — the substrate through which thought, matter, and communication flow. This project borrows that metaphor: a connective layer between human intent and implemented software.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Package management | uv |
| TUI | Textual |
| Code quality | ruff |
| Testing | pytest |
| Agent execution | Claude CLI in Docker sandbox |

## Repo Layout

```
keywork/
├── README.md                        # Brief intro, links here
├── CLAUDE.md                        # Agent reference and conventions
├── HUMANS.md                        # This file
├── pyproject.toml                   # Python package definition
├── .python-version                  # 3.11
├── .gitignore                       # workspace/, logs, .claude
├── Makefile                         # tui, setup, lint, test, clean
├── assets/
│   └── cover.png                    # Branding
│
├── keywork/                         # Python package (TUI + utilities)
│   ├── __init__.py
│   └── tui/
│       ├── __init__.py
│       ├── __main__.py              # Entry: python -m keywork.tui
│       ├── app.py                   # Main TUI app + widgets + screens
│       ├── state.py                 # File-based state reader
│       ├── screens.py               # Selection modal screens
│       ├── terminal.py              # Cross-platform terminal launcher
│       └── sandbox.py               # Docker sandbox manager
│
├── agents/                          # Agent system
│   ├── prompts/                     # Agent prompt templates
│   │   ├── plan.md                  # Planning: PRD → task checklist
│   │   ├── build.md                 # Building: implement one task
│   │   ├── final_gate.md            # Validation: check PRD conformance
│   │   ├── orchestrate.md           # Multi-goal scheduling
│   │   ├── create_prd.md            # Interactive PRD refinement
│   │   ├── promote.md               # Spec promotion to working repo
│   │   ├── feedback.md              # Human feedback capture
│   │   ├── retro.md                 # Post-completion retrospective
│   │   ├── repo_init.md             # Repo initialization interview
│   │   └── refs/
│   │       ├── feedback_rules.md    # How plan agent processes feedback
│   │       └── questions_rules.md   # How plan agent processes questions
│   ├── skills/                      # Bundled generic skills
│   │   ├── testing.md
│   │   ├── docker.md
│   │   ├── refactoring.md
│   │   ├── api_development.md
│   │   ├── documentation.md
│   │   └── ci_cd.md
│   ├── goals/                       # Goal state (per-goal directories)
│   │   ├── {goal-name}/
│   │   │   ├── state.md             # Status, priority, repo, counts
│   │   │   ├── prd.md               # Product Requirements Document
│   │   │   ├── IMPLEMENTATION.md    # Task checklist
│   │   │   ├── journal.md           # Build discoveries
│   │   │   ├── specs/               # Working specifications
│   │   │   ├── feedback.md          # Human feedback entries
│   │   │   ├── questions.md         # Agent information requests
│   │   │   ├── review.md            # Final gate findings
│   │   │   ├── session.log          # Build phase log
│   │   │   └── telemetry.jsonl      # Cost/duration metrics
│   │   ├── _completed/              # Archived completed goals
│   │   └── orchestrator.log         # Multi-goal activity log
│   ├── repos/                       # Repo registry
│   │   ├── _template/               # Template for new repos
│   │   │   ├── config.yaml
│   │   │   └── knowledge.md
│   │   └── {repo-name}/
│   │       ├── config.yaml          # Repo metadata and check commands
│   │       ├── knowledge.md         # Accumulated learnings
│   │       └── skills/              # Repo-specific skills (optional)
│   ├── sandbox/                     # Docker sandbox
│   │   ├── Dockerfile
│   │   ├── entrypoint.sh
│   │   ├── .env.example
│   │   └── setup.sh
│   ├── loop.sh                      # Plan/build/gate cycle
│   ├── orchestrate.sh               # Multi-goal orchestrator
│   ├── new_goal.sh                  # Create goal with repo association
│   ├── create_prd.sh                # Launch PRD agent
│   ├── feedback.sh                  # Feedback capture + resume
│   ├── retro.sh                     # Retrospective agent
│   ├── complete_goal.sh             # Finalize + promote specs
│   ├── repo_init.sh                 # Register + initialize a repo
│   └── report.py                    # Telemetry analysis
│
├── workspace/                       # Cloned working repos (gitignored)
│   └── .gitkeep
│
└── tests/
    ├── conftest.py
    └── test_tui/
```

## Local Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) installed
- Docker Desktop (or OrbStack) running
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) authenticated
- SSH key loaded (`ssh-add`)

### Install

```bash
uv sync --group dev
```

### First-time sandbox setup

```bash
bash agents/sandbox/setup.sh
```

This validates prerequisites, creates `.env`, checks credentials, and builds the Docker image.

### Launch TUI

```bash
make tui
```

Or directly:

```bash
uv run python -m keywork.tui
```

## Workflow

### 1. Register a repo

Via TUI: Press `m` (Manage Repos) → `a` (Add Repo) → enter name and git URL.

Via CLI:
```bash
bash agents/repo_init.sh my-project git@github.com:org/my-project.git
```

This clones the repo, runs an interactive initialization interview to discover architecture, conventions, and check commands, and produces a knowledge profile.

### 2. Create a goal

Via TUI: Press `n` (New Goal) → enter goal name → select target repo.

Via CLI:
```bash
bash agents/new_goal.sh add-user-auth my-project
```

### 3. Write the PRD

Edit `agents/goals/add-user-auth/prd.md` with a rough outline, then refine interactively:

```bash
bash agents/create_prd.sh add-user-auth
```

### 4. Run the build loop

Via TUI: Select goal → `b` (Build).

Via CLI:
```bash
bash agents/loop.sh add-user-auth
```

The loop runs plan → build → replan → build → ... → final gate → spec promotion.

### 5. Test and provide feedback

The loop pauses for human testing. Test the changes in `workspace/my-project/`, then:

Via TUI: Select goal → `f` (Quick feedback) or `F` (Interview feedback).

Via CLI:
```bash
bash agents/feedback.sh add-user-auth
bash agents/feedback.sh add-user-auth --resume
```

### 6. Complete the goal

Via TUI: Select goal → `C` (Complete).

Via CLI:
```bash
bash agents/complete_goal.sh add-user-auth
```

This promotes specs to the working repo's `docs/specs/`, runs a retrospective, and archives the goal.

### Multi-goal orchestration

Start the orchestrator to manage multiple goals across repos:

Via TUI: Press `s` (Start Orchestrator).

Via CLI:
```bash
bash agents/orchestrate.sh
```

The orchestrator scores goal priorities (including repo priority), selects the highest-priority action, and cycles through goals automatically.

## Goal Lifecycle

```
created ──→ planning ──→ building ──→ gate_review ──→ promoting ──→ completed
              ↑              │            │                           │
              └── replan ────┘            │                           │
              ↑                           │                           │
              └── remediation ────────────┘                           │
                                                                      ↓
                                                              _completed/
```

### States

| State | Description |
|-------|-------------|
| `created` | Goal directory exists, PRD may be empty |
| `planning` | Plan agent creating/updating IMPLEMENTATION.md |
| `building` | Build agent implementing tasks |
| `gate_review` | Final gate validating PRD conformance |
| `promoting` | Specs being promoted to working repo |
| `completed` | Goal archived to `_completed/` |
| `paused` | Human testing in progress (`.pause` file) |

### Signal files

| File | Effect |
|------|--------|
| `.pause` | Loop waits until file is removed |
| `.stop` | Loop exits immediately |
| `.replan` | Force replan on next cycle |

## TUI Keybindings

### Main dashboard

| Key | Action |
|-----|--------|
| `n` | New goal |
| `m` | Manage repos |
| `a` | Focus attention panel |
| `f` | Quick feedback |
| `s` | Start orchestrator |
| `x` | Stop orchestrator |
| `l` | Show build log |
| `r` | Refresh |
| `q` | Quit |

### Goal detail screen

| Key | Action |
|-----|--------|
| `c` | Create/refine PRD |
| `b` | Start build loop |
| `p` | Force plan |
| `g` | Force gate review |
| `q` | Answer questions |
| `f` | Quick feedback |
| `F` | Interview feedback |
| `t` | Retrospective |
| `C` | Complete goal |
| `w` | Pause |
| `W` | Resume |
| `x` | Stop |

## Telemetry

View cost and duration analysis for a goal:

```bash
python3 agents/report.py <goal-name>
```

Shows summary, per-phase breakdown, model usage, timeline, and insights.
