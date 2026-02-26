#!/bin/bash
set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────
GOAL_NAME="${1:-}"
if [ -z "$GOAL_NAME" ]; then
    echo "Usage: bash agents/feedback.sh <goal-name> [--resume]"
    echo ""
    echo "  Record feedback:  bash agents/feedback.sh <goal-name>"
    echo "  Resume loop:      bash agents/feedback.sh <goal-name> --resume"
    exit 1
fi

GOAL_DIR="agents/goals/$GOAL_NAME"

if [ ! -d "$GOAL_DIR" ]; then
    echo "Error: Goal '$GOAL_NAME' not found at $GOAL_DIR"
    echo "Create it with: bash agents/new_goal.sh $GOAL_NAME"
    exit 1
fi

if [ ! -f "$GOAL_DIR/IMPLEMENTATION.md" ]; then
    echo "Error: No IMPLEMENTATION.md found. Has the build loop run yet?"
    exit 1
fi

# ── Resume flag ──────────────────────────────────────────────────────
if [ "${2:-}" = "--resume" ]; then
    if [ -f "$GOAL_DIR/.pause" ]; then
        rm "$GOAL_DIR/.pause"
        echo "Pause removed. Loop will resume on next cycle."
    else
        echo "No pause file found — loop is not paused."
    fi
    exit 0
fi

# ── Initialise feedback.md if it doesn't exist ───────────────────────
if [ ! -f "$GOAL_DIR/feedback.md" ]; then
    cat > "$GOAL_DIR/feedback.md" << 'EOF'
# Human Feedback

<!-- Last incorporated: none -->
EOF
fi

# ── Run the feedback agent ───────────────────────────────────────────
PROMPT=$(sed "s|{GOAL_DIR}|$GOAL_DIR|g" agents/prompts/feedback.md)

CLAUDE_ARGS=(--system-prompt "$PROMPT")
if [ "${KEYWORK_SANDBOX:-}" = "1" ]; then
    CLAUDE_ARGS+=(--dangerously-skip-permissions)
fi

claude "${CLAUDE_ARGS[@]}" "Read the project context and ask me about my testing observations."

echo ""
echo "Feedback recorded in $GOAL_DIR/feedback.md"
echo ""
if [ -f "$GOAL_DIR/.pause" ]; then
    echo "The loop is paused. To resume:"
    echo "  bash agents/feedback.sh $GOAL_NAME --resume"
else
    echo "To act on this feedback, re-run the loop:"
    echo "  bash agents/loop.sh $GOAL_NAME"
fi
