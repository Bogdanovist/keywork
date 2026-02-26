#!/bin/bash
set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────
GOAL_NAME="${1:-}"
REPO_NAME="${2:-}"

if [ -z "$GOAL_NAME" ]; then
    echo "Usage: bash agents/new_goal.sh <goal-name> [repo-name]"
    echo ""
    echo "Examples:"
    echo "  bash agents/new_goal.sh auth-refactor my-api"
    echo "  bash agents/new_goal.sh dashboard-v2           # will prompt for repo"
    exit 1
fi

# ── Validate naming ──────────────────────────────────────────────────
if ! echo "$GOAL_NAME" | grep -qE '^[a-z][a-z0-9-]*$'; then
    echo "Error: Goal name must be kebab-case (lowercase letters, numbers, hyphens; must start with a letter)"
    echo "Example: auth-refactor, campaign-perf-dashboard, attribution-v2"
    exit 1
fi

GOAL_DIR="agents/goals/$GOAL_NAME"

# ── Check for conflicts ──────────────────────────────────────────────
if [ -d "$GOAL_DIR" ]; then
    echo "Error: Goal '$GOAL_NAME' already exists at $GOAL_DIR"
    exit 1
fi

if [ -d "agents/goals/_completed/$GOAL_NAME" ]; then
    echo "Warning: A completed goal named '$GOAL_NAME' exists at agents/goals/_completed/$GOAL_NAME"
    read -p "Create a new goal with this name anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ── Resolve repo ─────────────────────────────────────────────────────
if [ -z "$REPO_NAME" ]; then
    # List registered repos from agents/repos/
    REPOS_DIR="agents/repos"
    repos=()
    for d in "$REPOS_DIR"/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        [ "$name" = "_template" ] && continue
        [[ "$name" == .* ]] && continue
        repos+=("$name")
    done

    if [ ${#repos[@]} -eq 0 ]; then
        echo "Error: No repos registered in agents/repos/"
        echo "Register a repo first: bash agents/repo_init.sh <repo-name> [git-remote-url]"
        exit 1
    fi

    echo "Available repos:"
    for i in "${!repos[@]}"; do
        echo "  $((i + 1)). ${repos[$i]}"
    done
    echo ""
    read -p "Select repo (1-${#repos[@]}): " -r choice
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#repos[@]}" ]; then
        echo "Error: Invalid selection"
        exit 1
    fi
    REPO_NAME="${repos[$((choice - 1))]}"
fi

# ── Validate repo exists ─────────────────────────────────────────────
if [ ! -d "agents/repos/$REPO_NAME" ]; then
    echo "Error: Repo '$REPO_NAME' not found in agents/repos/"
    echo "Register it first: bash agents/repo_init.sh $REPO_NAME [git-remote-url]"
    exit 1
fi

if [ ! -d "workspace/$REPO_NAME" ]; then
    echo "Warning: Workspace not found at workspace/$REPO_NAME"
    echo "The repo is registered but the workspace directory is missing."
    read -p "Create goal anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ── Create goal structure ────────────────────────────────────────────
mkdir -p "$GOAL_DIR/specs"
touch "$GOAL_DIR/specs/.gitkeep"

cat > "$GOAL_DIR/state.md" << EOF
# Goal State

repo: $REPO_NAME
status: created
created: $(date +%Y-%m-%d)
priority: normal
last_activity: $(date -u +%Y-%m-%dT%H:%M:%S)
completed_tasks: 0
total_tasks: 0
blocked_tasks: 0
review_tasks: 0
total_cost_usd: 0.00
EOF

cat > "$GOAL_DIR/prd.md" << EOF
# $GOAL_NAME — Product Requirements

## Raw Outline
<!-- Write your rough description here. The create_prd agent will
     refine this into a complete PRD through interactive discussion. -->

## Problem Statement
<!-- What problem does this goal solve? -->

## Proposed Solution
<!-- High-level approach. -->

## Requirements

### Must Have

### Nice to Have

### Non-Requirements

## Success Metrics
<!-- How do we know this is done and working? -->

## Open Questions
<!-- Anything still unresolved. -->
EOF

cat > "$GOAL_DIR/journal.md" << 'EOF'
# Goal Journal

<!-- The build agent adds entries here when encountering noteworthy decisions,
     workarounds, or discoveries during implementation. Entries help the plan
     agent adjust on re-planning and feed into the retrospective at goal end. -->
EOF

# ── Done ──────────────────────────────────────────────────────────────
echo ""
echo "Goal '$GOAL_NAME' created (repo: $REPO_NAME)."
echo ""
echo "  Directory: $GOAL_DIR"
echo ""
echo "Next steps:"
echo "  1. Write your goal outline in $GOAL_DIR/prd.md"
echo "  2. Refine with the PRD agent:  bash agents/create_prd.sh $GOAL_NAME"
echo "  3. Start the build loop:       bash agents/loop.sh $GOAL_NAME"
