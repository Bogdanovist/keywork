#!/bin/bash
set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────
GOAL_NAME="${1:-}"
if [ -z "$GOAL_NAME" ]; then
    echo "Usage: bash agents/complete_goal.sh <goal-name>"
    exit 1
fi

GOAL_DIR="agents/goals/$GOAL_NAME"
COMPLETED_DIR="agents/goals/_completed/$GOAL_NAME"

if [ ! -d "$GOAL_DIR" ]; then
    echo "Error: Goal '$GOAL_NAME' not found at $GOAL_DIR"
    exit 1
fi

# ── Resolve repo context ─────────────────────────────────────────────
REPO_NAME=$(grep '^repo:' "$GOAL_DIR/state.md" | sed 's/^repo: *//' | head -1)
if [ -z "$REPO_NAME" ]; then
    echo "Error: No 'repo:' field found in $GOAL_DIR/state.md"
    exit 1
fi

WORKSPACE_DIR="workspace/$REPO_NAME"

# ── Safety checks ────────────────────────────────────────────────────

# Check for incomplete tasks
if [ -f "$GOAL_DIR/IMPLEMENTATION.md" ]; then
    INCOMPLETE=$(grep -c '^\- \[ \]' "$GOAL_DIR/IMPLEMENTATION.md" || true)
    if [ "$INCOMPLETE" -gt 0 ]; then
        echo "Warning: $INCOMPLETE incomplete task(s) remain in IMPLEMENTATION.md"
        read -p "Complete anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

# Check if retro has been run
if [ ! -f "$GOAL_DIR/.retro_done" ]; then
    echo "Warning: No retrospective has been run for this goal."
    echo "Consider running: bash agents/retro.sh $GOAL_NAME"
    read -p "Complete without retrospective? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if retro lessons have been actioned
if [ -f "$GOAL_DIR/retro_lessons.md" ]; then
    echo "Warning: $GOAL_DIR/retro_lessons.md still exists."
    echo "Action each lesson into its suggested destination, then delete the file."
    read -p "Complete with unactioned lessons? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ── Spec Promotion ───────────────────────────────────────────────────
if [ -d "$GOAL_DIR/specs" ] && [ "$(ls -A "$GOAL_DIR/specs" 2>/dev/null | grep -v .gitkeep)" ]; then
    echo ""
    echo "=== Promoting goal specs to workspace ==="
    CLAUDE_FLAGS="${CLAUDE_FLAGS:-}"

    # Build prompt with multi-variable substitution
    PROMPT=$(sed \
        -e "s|{GOAL_DIR}|$GOAL_DIR|g" \
        -e "s|{REPO_NAME}|$REPO_NAME|g" \
        -e "s|{WORKSPACE_DIR}|$WORKSPACE_DIR|g" \
        agents/prompts/promote.md)

    claude $CLAUDE_FLAGS -p --dangerously-skip-permissions "$PROMPT" || {
        echo "Warning: Spec promotion failed. You can run it manually later."
        echo "  The goal will still be completed."
    }

    # Commit spec changes in the working repo
    if [ -d "$WORKSPACE_DIR" ]; then
        (
            cd "$WORKSPACE_DIR" && \
            git add docs/specs/ 2>/dev/null && \
            git commit -m "docs: promote specs from goal $GOAL_NAME" --no-verify 2>/dev/null
        ) || true
        echo "Spec promotion complete."
    fi
else
    echo "No specs to promote."
fi

# ── Complete ─────────────────────────────────────────────────────────
if [ -d "$COMPLETED_DIR" ]; then
    echo "Error: Completed directory already exists at $COMPLETED_DIR"
    exit 1
fi

mkdir -p agents/goals/_completed
mv "$GOAL_DIR" "$COMPLETED_DIR"

echo ""
echo "Goal '$GOAL_NAME' completed and moved to $COMPLETED_DIR"
echo "Repo: $REPO_NAME"
