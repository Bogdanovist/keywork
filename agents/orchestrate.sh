#!/bin/bash
set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────
# Multi-goal orchestrator. Interleaves plan/build/gate cycles across
# all active goals in agents/goals/.
#
# Usage:
#   bash agents/orchestrate.sh                    # run until all goals complete or idle
#   bash agents/orchestrate.sh 10                 # limit to 10 cycles
#   MAX_COST_USD=50 bash agents/orchestrate.sh    # cost guardrail

MAX_ITERATIONS="${1:-${MAX_ITERATIONS:-50}}"
MAX_COST_USD="${MAX_COST_USD:-100}"
CLAUDE_FLAGS="${CLAUDE_FLAGS:-}"
REPLAN_INTERVAL="${REPLAN_INTERVAL:-5}"

# ── Dependencies ──────────────────────────────────────────────────────
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required for telemetry collection"
    echo "Install: brew install jq (macOS) or apt-get install jq (Linux)"
    exit 1
fi

# ── Validation ────────────────────────────────────────────────────────
GOALS_DIR="agents/goals"
if [ ! -d "$GOALS_DIR" ]; then
    echo "Error: $GOALS_DIR directory not found"
    exit 1
fi

# ── Repo helpers ──────────────────────────────────────────────────────

# Read repo name from a goal's state.md
goal_repo() {
    local goal_dir="$1"
    grep '^repo:' "$goal_dir/state.md" 2>/dev/null | sed 's/^repo: *//' | head -1
}

# Read repo priority from config.yaml (low=1, normal=2, high=3, urgent=4)
repo_priority_score() {
    local repo_name="$1"
    local config="agents/repos/$repo_name/config.yaml"
    local priority="normal"
    if [ -f "$config" ]; then
        priority=$(grep '^priority:' "$config" | sed 's/^priority: *//' | tr -d '"' | tr -d "'" | head -1)
    fi
    case "$priority" in
        low)    echo 1 ;;
        normal) echo 2 ;;
        high)   echo 3 ;;
        urgent) echo 4 ;;
        *)      echo 2 ;;
    esac
}

# Count active goals (directories excluding _completed and dotfiles)
active_goals() {
    local count=0
    for d in "$GOALS_DIR"/*/; do
        [ -d "$d" ] || continue
        local name
        name=$(basename "$d")
        [ "$name" = "_completed" ] && continue
        [[ "$name" == .* ]] && continue
        [ -f "$d/state.md" ] || continue
        local status
        status=$(grep '^status:' "$d/state.md" | awk '{print $2}')
        if [ "$status" != "completed" ] && [ "$status" != "created" ] && [ "$status" != "paused" ]; then
            count=$((count + 1))
        fi
    done
    echo "$count"
}

if [ "$(active_goals)" -eq 0 ]; then
    echo "No active goals found in $GOALS_DIR."
    echo "Create a goal with: bash agents/new_goal.sh <name> <repo>"
    exit 0
fi

# ── Telemetry ─────────────────────────────────────────────────────────
ORCHESTRATOR_LOG="$GOALS_DIR/orchestrator.log"
CUMULATIVE_COST=0.00

# Track which repos have active builds to enforce exclusivity
ACTIVE_REPO=""

# ── Agent invocation ─────────────────────────────────────────────────

run_agent() {
    local phase="$1"
    local prompt="$2"
    local goal_name="$3"
    local goal_dir="$GOALS_DIR/$goal_name"
    local telemetry_file="$goal_dir/telemetry.jsonl"
    local repo_name
    repo_name=$(goal_repo "$goal_dir")

    echo ""
    echo "=== [$phase] $goal_name ($repo_name) — $(date '+%H:%M:%S') ==="

    local output_file
    output_file=$(mktemp)

    local exit_code=0
    local attempt=1
    local max_attempts=2
    while [ $attempt -le $max_attempts ]; do
        exit_code=0
        claude --model opus $CLAUDE_FLAGS -p --output-format json "$prompt" > "$output_file" || exit_code=$?
        if [ $exit_code -eq 0 ]; then
            break
        fi
        if [ $attempt -lt $max_attempts ]; then
            echo "WARNING: claude exited with code $exit_code during '$phase' for $goal_name (attempt $attempt/$max_attempts). Retrying..."
            sleep 10
        fi
        attempt=$((attempt + 1))
    done

    if [ $exit_code -ne 0 ]; then
        echo "ERROR: '$phase' for $goal_name failed after $max_attempts attempts."
        rm -f "$output_file"
        return $exit_code
    fi

    # Print result
    jq -r '.result // empty' "$output_file" 2>/dev/null || cat "$output_file"

    # Session log
    local result_text
    result_text=$(jq -r '.result // empty' "$output_file" 2>/dev/null || true)
    if [ -n "$result_text" ]; then
        {
            echo "=== [$phase] $(date '+%Y-%m-%d %H:%M:%S') ==="
            echo "$result_text"
            echo ""
        } >> "$goal_dir/session.log"
    fi

    # Telemetry
    if jq -e '.usage' "$output_file" >/dev/null 2>&1; then
        local cost
        cost=$(jq -r '.total_cost_usd // 0' "$output_file")
        CUMULATIVE_COST=$(echo "$CUMULATIVE_COST + $cost" | bc 2>/dev/null || echo "$CUMULATIVE_COST")

        jq -c --arg goal "$goal_name" --arg phase "$phase" \
              --arg repo "$repo_name" \
              --argjson iteration "${CYCLE_COUNT:-0}" '{
            timestamp: (now | todate),
            goal: $goal,
            repo: $repo,
            phase: $phase,
            iteration: $iteration,
            duration_ms: .duration_ms,
            num_turns: .num_turns,
            total_cost_usd: .total_cost_usd,
            is_error: .is_error,
            session_id: .session_id,
            model_usage: .modelUsage
        }' "$output_file" >> "$telemetry_file" 2>/dev/null || true
    fi

    rm -f "$output_file"
    return 0
}

# ── Prompt construction ──────────────────────────────────────────────

build_prompt() {
    local template_file="$1"
    local goal_name="$2"
    local goal_dir="$GOALS_DIR/$goal_name"
    local repo_name
    repo_name=$(goal_repo "$goal_dir")
    local workspace_dir="workspace/$repo_name"
    local repo_config="agents/repos/$repo_name/config.yaml"

    local prompt
    prompt=$(sed \
        -e "s|{GOAL_DIR}|$goal_dir|g" \
        -e "s|{REPO_NAME}|$repo_name|g" \
        -e "s|{WORKSPACE_DIR}|$workspace_dir|g" \
        "$template_file")

    # Append repo CLAUDE.md as context
    if [ -f "$workspace_dir/CLAUDE.md" ]; then
        prompt="$prompt

---
## Repository Instructions (from CLAUDE.md)

$(cat "$workspace_dir/CLAUDE.md")"
    fi

    # Append repo knowledge.md as context
    local knowledge_md="agents/repos/$repo_name/knowledge.md"
    if [ -f "$knowledge_md" ]; then
        prompt="$prompt

---
## Repository Knowledge

$(cat "$knowledge_md")"
    fi

    # Append check commands
    if [ -f "$repo_config" ]; then
        local checks_section=""
        local lint test typecheck build_cmd
        lint=$(grep '^ *lint:' "$repo_config" | sed 's/^ *lint: *//' | tr -d '"' | tr -d "'" | head -1)
        test=$(grep '^ *test:' "$repo_config" | sed 's/^ *test: *//' | tr -d '"' | tr -d "'" | head -1)
        typecheck=$(grep '^ *typecheck:' "$repo_config" | sed 's/^ *typecheck: *//' | tr -d '"' | tr -d "'" | head -1)
        build_cmd=$(grep '^ *build:' "$repo_config" | sed 's/^ *build: *//' | tr -d '"' | tr -d "'" | head -1)

        [ -n "$lint" ] && checks_section="${checks_section}
- Lint: \`$lint\`"
        [ -n "$test" ] && checks_section="${checks_section}
- Test: \`$test\`"
        [ -n "$typecheck" ] && checks_section="${checks_section}
- Typecheck: \`$typecheck\`"
        [ -n "$build_cmd" ] && checks_section="${checks_section}
- Build: \`$build_cmd\`"

        if [ -n "$checks_section" ]; then
            prompt="$prompt

---
## Check Commands
$checks_section"
        fi
    fi

    echo "$prompt"
}

# ── Action executors ─────────────────────────────────────────────────

run_plan() {
    local goal_name="$1"
    local goal_dir="$GOALS_DIR/$goal_name"
    local prompt
    prompt=$(build_prompt agents/prompts/plan.md "$goal_name")
    run_agent "plan" "$prompt" "$goal_name"
    rm -f "$goal_dir/.replan"
    update_state "$goal_name" "building"
}

run_build() {
    local goal_name="$1"
    local goal_dir="$GOALS_DIR/$goal_name"
    local prompt
    prompt=$(build_prompt agents/prompts/build.md "$goal_name")
    run_agent "build" "$prompt" "$goal_name"
}

run_gate() {
    local goal_name="$1"
    local goal_dir="$GOALS_DIR/$goal_name"
    local prompt
    prompt=$(build_prompt agents/prompts/final_gate.md "$goal_name")
    run_agent "gate" "$prompt" "$goal_name"
    update_state "$goal_name" "gate_review"
}

run_promote() {
    local goal_name="$1"
    local goal_dir="$GOALS_DIR/$goal_name"
    local prompt
    prompt=$(build_prompt agents/prompts/promote.md "$goal_name")
    run_agent "promote" "$prompt" "$goal_name"
    update_state "$goal_name" "completed"

    # Move to _completed
    mkdir -p "$GOALS_DIR/_completed"
    mv "$goal_dir" "$GOALS_DIR/_completed/$goal_name"
    echo "Goal '$goal_name' completed and moved to _completed/"
}

# ── State management ──────────────────────────────────────────────────

update_state() {
    local goal_name="$1"
    local new_status="$2"
    local state_file="$GOALS_DIR/$goal_name/state.md"

    if [ -f "$state_file" ]; then
        # Update status line
        if grep -q '^status:' "$state_file"; then
            sed -i '' "s/^status:.*/status: $new_status/" "$state_file"
        fi
        # Update last_activity
        if grep -q '^last_activity:' "$state_file"; then
            sed -i '' "s/^last_activity:.*/last_activity: $(date -u +%Y-%m-%dT%H:%M:%S)/" "$state_file"
        fi
        # Update task counts from IMPLEMENTATION.md
        local impl="$GOALS_DIR/$goal_name/IMPLEMENTATION.md"
        if [ -f "$impl" ]; then
            local total completed blocked review
            total=$(grep -c '^\- \[' "$impl" || true)
            completed=$(grep -c '^\- \[x\]' "$impl" || true)
            blocked=$(grep -c '^\- \[BLOCKED' "$impl" || true)
            review=$(grep -c '^\- \[REVIEW' "$impl" || true)
            sed -i '' "s/^total_tasks:.*/total_tasks: $total/" "$state_file"
            sed -i '' "s/^completed_tasks:.*/completed_tasks: $completed/" "$state_file"
            sed -i '' "s/^blocked_tasks:.*/blocked_tasks: $blocked/" "$state_file"
            sed -i '' "s/^review_tasks:.*/review_tasks: $review/" "$state_file"
        fi
    fi
}

# ── Dual commit: commit state changes to keywork repo ────────────────

commit_state() {
    local goal_name="$1"
    local phase="$2"
    git add "agents/goals/$goal_name/" 2>/dev/null || true
    git commit -m "State: $phase for $goal_name" --no-verify 2>/dev/null || true
}

# ── Orchestrator decision ────────────────────────────────────────────

run_orchestrator_decision() {
    local prompt
    prompt=$(cat agents/prompts/orchestrate.md)

    # Append repo context for each active goal
    local repo_context=""
    for d in "$GOALS_DIR"/*/; do
        [ -d "$d" ] || continue
        local name
        name=$(basename "$d")
        [ "$name" = "_completed" ] && continue
        [[ "$name" == .* ]] && continue
        [ -f "$d/state.md" ] || continue
        local repo
        repo=$(goal_repo "$d")
        if [ -n "$repo" ]; then
            local score
            score=$(repo_priority_score "$repo")
            repo_context="${repo_context}
- Goal '$name' targets repo '$repo' (priority score: $score)"
        fi
    done

    if [ -n "$repo_context" ]; then
        prompt="$prompt

---
## Repo Context
$repo_context

IMPORTANT: Do not schedule two goals targeting the same repo simultaneously.
Active repo with running build: ${ACTIVE_REPO:-none}"
    fi

    local output_file
    output_file=$(mktemp)

    # Use sonnet for the scheduling decision (faster, cheaper)
    claude --model sonnet $CLAUDE_FLAGS -p --output-format json "$prompt" > "$output_file" 2>/dev/null || {
        echo "ERROR: Orchestrator agent failed"
        rm -f "$output_file"
        echo "ACTION: idle"
        echo "REASON: Orchestrator agent error"
        return 1
    }

    local result
    result=$(jq -r '.result // empty' "$output_file" 2>/dev/null || cat "$output_file")
    rm -f "$output_file"

    echo "$result"
}

parse_decision() {
    local decision="$1"
    local field="$2"
    echo "$decision" | grep "^${field}:" | sed "s/^${field}: *//" | head -1
}

# ── Stop/pause checks ────────────────────────────────────────────────

check_global_stop() {
    # Check for stop files in any active goal
    for d in "$GOALS_DIR"/*/; do
        [ -d "$d" ] || continue
        local name
        name=$(basename "$d")
        [ "$name" = "_completed" ] && continue
        if [ -f "$d/.stop" ]; then
            local reason
            reason=$(cat "$d/.stop" 2>/dev/null || true)
            echo "STOPPED: $name — ${reason:-no reason given}"
            rm -f "$d/.stop"
            return 0
        fi
    done
    return 1
}

# ── Repo exclusivity check ───────────────────────────────────────────

check_repo_exclusivity() {
    local goal_name="$1"
    local goal_dir="$GOALS_DIR/$goal_name"
    local repo
    repo=$(goal_repo "$goal_dir")

    if [ -n "$ACTIVE_REPO" ] && [ "$repo" = "$ACTIVE_REPO" ]; then
        echo "SKIP: repo '$repo' already has an active build"
        return 1
    fi
    return 0
}

# ── Main loop ─────────────────────────────────────────────────────────
echo "================================================================"
echo "  Keywork Orchestrator"
echo "  Max cycles: $MAX_ITERATIONS  |  Cost limit: \$$MAX_COST_USD"
echo "================================================================"
echo ""

# List active goals with repo info
echo "Active goals:"
for d in "$GOALS_DIR"/*/; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    [ "$name" = "_completed" ] && continue
    [[ "$name" == .* ]] && continue
    [ -f "$d/state.md" ] || continue
    status=$(grep '^status:' "$d/state.md" | awk '{print $2}')
    priority=$(grep '^priority:' "$d/state.md" | awk '{print $2}')
    repo=$(goal_repo "$d")
    echo "  [$status] $name -> $repo (priority: $priority)"
done
echo ""

CYCLE_COUNT=0
IDLE_COUNT=0
LAST_GOAL=""

while [ $CYCLE_COUNT -lt "$MAX_ITERATIONS" ]; do
    CYCLE_COUNT=$((CYCLE_COUNT + 1))

    # ── Stop check ────────────────────────────────────────────────
    if check_global_stop; then
        echo "=== ORCHESTRATOR STOPPED ==="
        exit 0
    fi

    # ── Cost check ────────────────────────────────────────────────
    if echo "$CUMULATIVE_COST > $MAX_COST_USD" | bc -l 2>/dev/null | grep -q '^1'; then
        echo "=== COST LIMIT REACHED (\$$CUMULATIVE_COST > \$$MAX_COST_USD) ==="
        exit 1
    fi

    # ── Get orchestrator decision ─────────────────────────────────
    echo "--- Cycle $CYCLE_COUNT/$MAX_ITERATIONS (cost: \$$CUMULATIVE_COST) ---"

    DECISION=$(run_orchestrator_decision)

    action=$(parse_decision "$DECISION" "ACTION")
    goal=$(parse_decision "$DECISION" "GOAL")
    reason=$(parse_decision "$DECISION" "REASON")
    state_update=$(parse_decision "$DECISION" "STATE_UPDATE")

    echo "Decision: [$action] $goal — $reason"
    echo "$(date '+%Y-%m-%d %H:%M:%S') | cycle=$CYCLE_COUNT | goal=$goal | action=$action | reason=$reason" >> "$ORCHESTRATOR_LOG"

    # ── Handle idle ───────────────────────────────────────────────
    if [ "$action" = "idle" ]; then
        IDLE_COUNT=$((IDLE_COUNT + 1))
        if [ $IDLE_COUNT -ge 3 ]; then
            echo "=== ORCHESTRATOR IDLE (3 consecutive idle cycles) ==="
            exit 0
        fi
        echo "Idle ($IDLE_COUNT/3). Waiting 30 seconds..."
        sleep 30
        continue
    fi
    IDLE_COUNT=0

    # ── Validate goal exists ──────────────────────────────────────
    if [ -z "$goal" ] || [ ! -d "$GOALS_DIR/$goal" ]; then
        echo "WARNING: Orchestrator selected invalid goal '$goal'. Skipping."
        continue
    fi

    # ── Repo exclusivity check ────────────────────────────────────
    if [ "$action" = "build" ] || [ "$action" = "gate" ]; then
        goal_dir_check="$GOALS_DIR/$goal"
        goal_repo_name=$(goal_repo "$goal_dir_check")
        if ! check_repo_exclusivity "$goal"; then
            echo "Skipping: repo '$goal_repo_name' already has active build."
            continue
        fi
        ACTIVE_REPO="$goal_repo_name"
    fi

    # ── Update state if requested ─────────────────────────────────
    if [ -n "$state_update" ]; then
        update_state "$goal" "$state_update"
    fi

    # ── Execute action ────────────────────────────────────────────
    case "$action" in
        plan)
            run_plan "$goal" || echo "WARNING: Plan failed for $goal"
            commit_state "$goal" "plan"
            ;;
        build)
            run_build "$goal" || echo "WARNING: Build failed for $goal"
            update_state "$goal" "building"
            commit_state "$goal" "build"
            ACTIVE_REPO=""
            ;;
        gate)
            run_gate "$goal" || echo "WARNING: Gate failed for $goal"
            commit_state "$goal" "gate"
            ACTIVE_REPO=""
            ;;
        promote)
            run_promote "$goal" || echo "WARNING: Promote failed for $goal"
            commit_state "$goal" "promote"
            ;;
        complete)
            # Move to completed
            mkdir -p "$GOALS_DIR/_completed"
            if [ -d "$GOALS_DIR/$goal" ]; then
                mv "$GOALS_DIR/$goal" "$GOALS_DIR/_completed/$goal"
                echo "Goal '$goal' moved to _completed/"
            fi
            ;;
        skip)
            echo "Skipping $goal: $reason"
            ;;
        *)
            echo "WARNING: Unknown action '$action'. Skipping."
            ;;
    esac

    LAST_GOAL="$goal"

    # ── Check if any active goals remain ──────────────────────────
    if [ "$(active_goals)" -eq 0 ]; then
        echo ""
        echo "=== ALL GOALS COMPLETE ==="
        exit 0
    fi
done

echo ""
echo "=== MAX CYCLES REACHED ($MAX_ITERATIONS) ==="
echo "Cumulative cost: \$$CUMULATIVE_COST"
exit 0
