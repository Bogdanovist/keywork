#!/bin/bash
set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────
GOAL_NAME="${1:-}"
if [ -z "$GOAL_NAME" ]; then
    echo "Usage: bash agents/create_prd.sh <goal-name>"
    exit 1
fi

GOAL_DIR="agents/goals/$GOAL_NAME"

if [ ! -d "$GOAL_DIR" ]; then
    echo "Error: Goal '$GOAL_NAME' not found at $GOAL_DIR"
    echo "Create it with: bash agents/new_goal.sh $GOAL_NAME"
    exit 1
fi

if [ ! -f "$GOAL_DIR/prd.md" ]; then
    echo "Error: No prd.md found at $GOAL_DIR/prd.md"
    exit 1
fi

# ── Run the create_prd agent ─────────────────────────────────────────
PROMPT=$(sed "s|{GOAL_DIR}|$GOAL_DIR|g" agents/prompts/create_prd.md)

CLAUDE_ARGS=(--system-prompt "$PROMPT")
if [ "${KEYWORK_SANDBOX:-}" = "1" ]; then
    CLAUDE_ARGS+=(--dangerously-skip-permissions)
fi

claude "${CLAUDE_ARGS[@]}" "Read the goal outline and begin the PRD creation process."
