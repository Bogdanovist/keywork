#!/bin/bash
set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────
GOAL_NAME="${1:-}"
if [ -z "$GOAL_NAME" ]; then
    echo "Usage: bash agents/retro.sh <goal-name>"
    exit 1
fi

GOAL_DIR="agents/goals/$GOAL_NAME"

if [ ! -d "$GOAL_DIR" ]; then
    echo "Error: Goal '$GOAL_NAME' not found at $GOAL_DIR"
    exit 1
fi

if [ ! -f "$GOAL_DIR/IMPLEMENTATION.md" ]; then
    echo "Error: No IMPLEMENTATION.md found at $GOAL_DIR/IMPLEMENTATION.md"
    echo "Has this goal been through the build loop?"
    exit 1
fi

# Allow injecting CLI flags (e.g. --dangerously-skip-permissions in sandbox)
CLAUDE_FLAGS="${CLAUDE_FLAGS:-}"

# ── Run the retro agent ──────────────────────────────────────────────
PROMPT=$(sed "s|{GOAL_DIR}|$GOAL_DIR|g" agents/prompts/retro.md)

CLAUDE_ARGS=($CLAUDE_FLAGS -p --dangerously-skip-permissions)
if [ "${KEYWORK_SANDBOX:-}" = "1" ]; then
    true  # flags already handle sandbox
fi

claude ${CLAUDE_ARGS[@]} "$PROMPT"

echo ""
echo "Retrospective complete."
echo "Review $GOAL_DIR/retro_lessons.md and action each lesson into its suggested destination."
echo "Once all lessons are actioned, delete the file and commit."
