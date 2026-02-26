#!/bin/bash
set -euo pipefail

# ── Sandbox trampoline ───────────────────────────────────────────────
# If we're already inside the Docker sandbox, skip straight to the loop.
# On the host, this section builds the image and re-execs inside a container.
if [ "${KEYWORK_SANDBOX:-}" != "1" ]; then

    # -- Shell access ------------------------------------------------
    if [ "${1:-}" = "--shell" ]; then
        SANDBOX_CMD=(bash)
        shift
    else
        SANDBOX_CMD=(bash agents/loop.sh "$@")
    fi

    # -- Docker prerequisite -----------------------------------------
    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: Docker is required to run the agent loop."
        echo "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
        exit 1
    fi

    # -- Paths -------------------------------------------------------
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
    SANDBOX_DIR="$SCRIPT_DIR/sandbox"

    # -- Validate host credentials -----------------------------------
    CLAUDE_DIR="$HOME/.claude"

    # On macOS, Claude Code stores credentials in the Keychain, not in
    # .credentials.json. Docker can't access the Keychain, so we export
    # the credentials to a file that gets mounted into the container.
    if [ "$(uname)" = "Darwin" ]; then
        KEYCHAIN_CREDS=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || true)
        if [ -n "$KEYCHAIN_CREDS" ]; then
            mkdir -p "$CLAUDE_DIR"
            echo "$KEYCHAIN_CREDS" > "$CLAUDE_DIR/.credentials.json"
            chmod 600 "$CLAUDE_DIR/.credentials.json"
        fi
    fi

    if [ ! -f "$CLAUDE_DIR/.credentials.json" ]; then
        echo "ERROR: Claude credentials not found."
        echo "Run 'claude' on the host first to authenticate."
        exit 1
    fi

    # Check if the exported token is expired
    if command -v jq >/dev/null 2>&1; then
        expires_at=$(jq -r '.claudeAiOauth.expiresAt // empty' "$CLAUDE_DIR/.credentials.json" 2>/dev/null)
        if [ -n "$expires_at" ]; then
            now_ms=$(python3 -c "import time; print(int(time.time() * 1000))")
            if [ "$expires_at" -le "$now_ms" ] 2>/dev/null; then
                echo "ERROR: Claude OAuth token has expired."
                echo "  Run 'claude' in your terminal to re-authenticate, then retry."
                exit 1
            fi
            # Warn if token expires within 30 minutes (agent runs can be long)
            margin_ms=$((30 * 60 * 1000))
            if [ "$((expires_at - now_ms))" -le "$margin_ms" ] 2>/dev/null; then
                remaining_min=$(( (expires_at - now_ms) / 60000 ))
                echo "WARNING: Claude OAuth token expires in ~${remaining_min} minutes."
                echo "  Consider running 'claude' on the host to refresh before a long session."
            fi
        fi
    fi

    # -- Resolve goal and repo for mount setup -----------------------
    GOAL_NAME_FOR_MOUNT="${1:-${GOAL_NAME:-}}"
    if [ -z "$GOAL_NAME_FOR_MOUNT" ]; then
        echo "Usage: bash agents/loop.sh <goal-name> [max-iterations]"
        echo "       bash agents/loop.sh <goal-name> <plan|build|final_gate> [count]"
        echo "   or: GOAL_NAME=foo bash agents/loop.sh"
        exit 1
    fi
    GOAL_DIR_FOR_MOUNT="agents/goals/$GOAL_NAME_FOR_MOUNT"
    if [ ! -d "$REPO_DIR/$GOAL_DIR_FOR_MOUNT" ]; then
        echo "Error: Goal '$GOAL_NAME_FOR_MOUNT' not found at $GOAL_DIR_FOR_MOUNT"
        exit 1
    fi

    # Read repo name from state.md
    REPO_NAME_FOR_MOUNT=$(grep '^repo:' "$REPO_DIR/$GOAL_DIR_FOR_MOUNT/state.md" | sed 's/^repo: *//' | head -1)
    if [ -z "$REPO_NAME_FOR_MOUNT" ]; then
        echo "Error: No 'repo:' field found in $GOAL_DIR_FOR_MOUNT/state.md"
        exit 1
    fi
    WORKSPACE_FOR_MOUNT="$REPO_DIR/workspace/$REPO_NAME_FOR_MOUNT"
    if [ ! -d "$WORKSPACE_FOR_MOUNT" ]; then
        echo "Error: Workspace not found at workspace/$REPO_NAME_FOR_MOUNT"
        echo "Register the repo first: bash agents/repo_init.sh $REPO_NAME_FOR_MOUNT"
        exit 1
    fi

    # -- Build image -------------------------------------------------
    IMAGE_NAME="keywork-sandbox"
    if [ -f "$SANDBOX_DIR/Dockerfile" ]; then
        echo "=== Building sandbox image ==="
        docker build -t "$IMAGE_NAME" -f "$SANDBOX_DIR/Dockerfile" "$SANDBOX_DIR"
    else
        echo "Warning: No Dockerfile at $SANDBOX_DIR/Dockerfile — expecting image '$IMAGE_NAME' to exist."
        if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
            echo "Error: Image '$IMAGE_NAME' not found. Create agents/sandbox/Dockerfile first."
            exit 1
        fi
    fi

    # -- Env file ----------------------------------------------------
    ENV_FILE_ARGS=()
    if [ -f "$SANDBOX_DIR/.env" ]; then
        ENV_FILE_ARGS=(--env-file "$SANDBOX_DIR/.env")
    fi

    # -- SSH agent forwarding ----------------------------------------
    SSH_ARGS=()
    if [ "$(uname)" = "Darwin" ]; then
        SSH_ARGS=(
            -v /run/host-services/ssh-auth.sock:/run/host-services/ssh-auth.sock
            -e SSH_AUTH_SOCK=/run/host-services/ssh-auth.sock
        )
    else
        if [ -n "${SSH_AUTH_SOCK:-}" ]; then
            SSH_ARGS=(
                -v "$SSH_AUTH_SOCK:/tmp/ssh-agent.sock"
                -e SSH_AUTH_SOCK=/tmp/ssh-agent.sock
            )
        fi
    fi

    # -- Repo-specific sandbox env vars ------------------------------
    REPO_CONFIG="$REPO_DIR/agents/repos/$REPO_NAME_FOR_MOUNT/config.yaml"
    EXTRA_ENV_ARGS=()
    if [ -f "$REPO_CONFIG" ]; then
        # Parse sandbox.env_vars from config.yaml (simple line-by-line)
        in_env_vars=0
        while IFS= read -r line; do
            if echo "$line" | grep -q '^ *env_vars:'; then
                in_env_vars=1
                continue
            fi
            if [ "$in_env_vars" -eq 1 ]; then
                if echo "$line" | grep -qE '^ *- '; then
                    var=$(echo "$line" | sed 's/^ *- *//' | tr -d '"' | tr -d "'")
                    if [ -n "$var" ]; then
                        EXTRA_ENV_ARGS+=(-e "$var")
                    fi
                else
                    in_env_vars=0
                fi
            fi
        done < "$REPO_CONFIG"
    fi

    # -- Forward host env overrides ----------------------------------
    PASSTHROUGH_ARGS=()
    for var in MAX_ITERATIONS REPLAN_INTERVAL MAX_COST_USD; do
        if [ -n "${!var:-}" ]; then
            PASSTHROUGH_ARGS+=(-e "$var=${!var}")
        fi
    done

    # -- TTY detection -----------------------------------------------
    TTY_ARGS=(--interactive)
    if [ -t 0 ]; then
        TTY_ARGS+=(--tty)
    fi

    # -- Launch container --------------------------------------------
    echo "=== Starting sandbox container ==="
    exec docker run \
        --name "keywork-agent-$$" \
        --rm \
        "${TTY_ARGS[@]}" \
        \
        -v "$WORKSPACE_FOR_MOUNT:/workspace" \
        -v "$REPO_DIR/$GOAL_DIR_FOR_MOUNT:/state" \
        -v "$REPO_DIR/agents:/agents:ro" \
        -v "$CLAUDE_DIR:/home/agent/.claude-host:ro" \
        \
        -v keywork-cache:/home/agent/.cache \
        \
        -e KEYWORK_SANDBOX=1 \
        -e CLAUDE_FLAGS="--dangerously-skip-permissions" \
        -e GOAL_NAME="$GOAL_NAME_FOR_MOUNT" \
        -e REPO_NAME="$REPO_NAME_FOR_MOUNT" \
        \
        ${ENV_FILE_ARGS[@]+"${ENV_FILE_ARGS[@]}"} \
        ${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"} \
        ${SSH_ARGS[@]+"${SSH_ARGS[@]}"} \
        ${EXTRA_ENV_ARGS[@]+"${EXTRA_ENV_ARGS[@]}"} \
        \
        "$IMAGE_NAME" \
        "${SANDBOX_CMD[@]}"
fi
# ── End trampoline ───────────────────────────────────────────────────

# ── Arguments ─────────────────────────────────────────────────────────
# $1 = goal name (required, or falls back to $GOAL_NAME env var)
# $2 = max iterations (optional, default from $MAX_ITERATIONS or 20)
GOAL_NAME="${1:-${GOAL_NAME:-}}"
if [ -z "$GOAL_NAME" ]; then
    echo "Usage: bash agents/loop.sh <goal-name> [max-iterations]"
    echo "       bash agents/loop.sh <goal-name> <plan|build|final_gate> [count]"
    echo "   or: GOAL_NAME=foo bash agents/loop.sh"
    exit 1
fi

# Goal name must be kebab-case (important for sed safety in prompt substitution)
GOAL_DIR="agents/goals/$GOAL_NAME"

# ── Resolve repo context ─────────────────────────────────────────────
REPO_NAME="${REPO_NAME:-}"
if [ -z "$REPO_NAME" ]; then
    REPO_NAME=$(grep '^repo:' "$GOAL_DIR/state.md" | sed 's/^repo: *//' | head -1)
fi
if [ -z "$REPO_NAME" ]; then
    echo "Error: No 'repo:' field found in $GOAL_DIR/state.md"
    exit 1
fi

WORKSPACE_DIR="workspace/$REPO_NAME"
REPO_CONFIG="agents/repos/$REPO_NAME/config.yaml"

# In-container, sandbox mounts override host paths
if [ "${KEYWORK_SANDBOX:-}" = "1" ]; then
    CONTAINER_GOAL_DIR="/state"
    CONTAINER_WORKSPACE="/workspace"
else
    CONTAINER_GOAL_DIR="$GOAL_DIR"
    CONTAINER_WORKSPACE="$WORKSPACE_DIR"
fi

# Detect phase override: loop.sh <name> <plan|build|final_gate> [count]
FORCED_PHASE=""
if [[ "${2:-}" =~ ^(plan|build|final_gate)$ ]]; then
    FORCED_PHASE="$2"
    MAX_ITERATIONS="${3:-1}"
else
    MAX_ITERATIONS="${2:-${MAX_ITERATIONS:-20}}"
fi

# Allow injecting CLI flags (e.g. --dangerously-skip-permissions in sandbox)
CLAUDE_FLAGS="${CLAUDE_FLAGS:-}"

# Cadence: how many builds between forced re-plans
REPLAN_INTERVAL="${REPLAN_INTERVAL:-5}"

# Cost guardrail: stop the loop if cumulative cost exceeds this (USD)
MAX_COST_USD="${MAX_COST_USD:-100}"

if [ "$REPLAN_INTERVAL" -lt 1 ] 2>/dev/null; then
    echo "Warning: REPLAN_INTERVAL must be >= 1, defaulting to 5"
    REPLAN_INTERVAL=5
fi

# ── Dependencies ──────────────────────────────────────────────────────
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required for telemetry collection"
    echo "Install: brew install jq (macOS) or apt-get install jq (Linux)"
    exit 1
fi

# ── Validation ────────────────────────────────────────────────────────
if [ ! -d "$GOAL_DIR" ]; then
    echo "Error: Goal '$GOAL_NAME' not found at $GOAL_DIR"
    echo "Create it with: bash agents/new_goal.sh $GOAL_NAME"
    exit 1
fi

if [ ! -s "$GOAL_DIR/prd.md" ]; then
    echo "Error: PRD is empty at $GOAL_DIR/prd.md"
    echo "Write your goal requirements before running the loop."
    exit 1
fi

if [ ! -d "$WORKSPACE_DIR" ] && [ "${KEYWORK_SANDBOX:-}" != "1" ]; then
    echo "Error: Workspace not found at $WORKSPACE_DIR"
    echo "Register the repo first: bash agents/repo_init.sh $REPO_NAME"
    exit 1
fi

# ── Parse check commands from config.yaml ────────────────────────────
parse_check_cmd() {
    local check_name="$1"
    if [ -f "$REPO_CONFIG" ]; then
        grep "^ *${check_name}:" "$REPO_CONFIG" | sed "s/^ *${check_name}: *//" | tr -d '"' | tr -d "'" | head -1
    fi
}

CHECK_LINT=$(parse_check_cmd "lint")
CHECK_TEST=$(parse_check_cmd "test")
CHECK_TYPECHECK=$(parse_check_cmd "typecheck")
CHECK_BUILD=$(parse_check_cmd "build")

# ── Telemetry ─────────────────────────────────────────────────────────
# Each agent invocation writes a JSONL record to $GOAL_DIR/telemetry.jsonl
# containing: timestamp, phase, iteration, duration, cost, turns, model usage.
# View with: python3 agents/report.py <goal-name>
TELEMETRY_FILE="$GOAL_DIR/telemetry.jsonl"

run_agent() {
    local phase="$1"
    local prompt="$2"
    local output_file
    output_file=$(mktemp)

    # Run agent with JSON output; stderr passes through for human monitoring.
    # Retry once on transient failures (network errors, API 5xx) before giving up.
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
            echo ""
            echo "WARNING: claude exited with code $exit_code during '$phase' phase (attempt $attempt/$max_attempts)."
            echo "Retrying in 10 seconds..."
            sleep 10
        fi
        attempt=$((attempt + 1))
    done

    if [ $exit_code -ne 0 ]; then
        echo ""
        echo "ERROR: claude exited with code $exit_code during '$phase' phase (after $max_attempts attempts)."
        echo "--- claude output ---"
        cat "$output_file"
        echo "--- end output ---"
        echo ""
        echo "Common causes:"
        echo "  - Expired OAuth token: run 'claude' on the host to re-authenticate"
        echo "  - Network issue: check connectivity"
        echo "  - API error: check stderr output above"
        rm -f "$output_file"
        return $exit_code
    fi

    # Print result text so humans can still see what happened
    jq -r '.result // empty' "$output_file" 2>/dev/null || cat "$output_file"

    # Persist result summary to session log
    local result_text
    result_text=$(jq -r '.result // empty' "$output_file" 2>/dev/null || true)
    if [ -n "$result_text" ]; then
        {
            echo "=== [$phase] $(date '+%Y-%m-%d %H:%M:%S') | iteration=${BUILD_COUNT:-0} ==="
            echo "$result_text"
            echo ""
        } >> "$GOAL_DIR/session.log"
    fi

    # Append telemetry record (best-effort — never breaks the loop)
    if jq -e '.usage' "$output_file" >/dev/null 2>&1; then
        jq -c --arg goal "$GOAL_NAME" --arg phase "$phase" \
              --arg repo "$REPO_NAME" \
              --argjson iteration "${BUILD_COUNT:-0}" '{
            timestamp: (now | todate),
            goal: $goal,
            repo: $repo,
            phase: $phase,
            iteration: $iteration,
            duration_ms: .duration_ms,
            duration_api_ms: .duration_api_ms,
            num_turns: .num_turns,
            total_cost_usd: .total_cost_usd,
            is_error: .is_error,
            session_id: .session_id,
            model_usage: .modelUsage
        }' "$output_file" >> "$TELEMETRY_FILE" 2>/dev/null || true
    fi

    rm -f "$output_file"
    return 0
}

# ── Helper functions ──────────────────────────────────────────────────

feedback_checksum() {
    if [ -f "$GOAL_DIR/feedback.md" ]; then
        if command -v md5sum >/dev/null 2>&1; then
            md5sum "$GOAL_DIR/feedback.md" | cut -d' ' -f1
        else
            md5 -q "$GOAL_DIR/feedback.md"
        fi
    else
        echo "none"
    fi
}

questions_checksum() {
    if [ -f "$GOAL_DIR/questions.md" ]; then
        if command -v md5sum >/dev/null 2>&1; then
            md5sum "$GOAL_DIR/questions.md" | cut -d' ' -f1
        else
            md5 -q "$GOAL_DIR/questions.md"
        fi
    else
        echo "none"
    fi
}

impl_checksum() {
    if [ -f "$GOAL_DIR/IMPLEMENTATION.md" ]; then
        if command -v md5sum >/dev/null 2>&1; then
            md5sum "$GOAL_DIR/IMPLEMENTATION.md" | cut -d' ' -f1
        else
            md5 -q "$GOAL_DIR/IMPLEMENTATION.md"
        fi
    else
        echo "none"
    fi
}

state_checksum() {
    # Checksum all goal state files to detect changes for dual-commit
    if command -v md5sum >/dev/null 2>&1; then
        find "$GOAL_DIR" -type f -not -name '*.log' -not -name 'telemetry.jsonl' | sort | xargs md5sum 2>/dev/null | md5sum | cut -d' ' -f1
    else
        find "$GOAL_DIR" -type f -not -name '*.log' -not -name 'telemetry.jsonl' | sort | xargs md5 -q 2>/dev/null | md5 -q
    fi
}

count_blocked_tasks() {
    if [ -f "$GOAL_DIR/IMPLEMENTATION.md" ]; then
        grep -c '^\- \[BLOCKED' "$GOAL_DIR/IMPLEMENTATION.md" || true
    else
        echo "0"
    fi
}

count_review_tasks() {
    if [ -f "$GOAL_DIR/IMPLEMENTATION.md" ]; then
        grep -c '^\- \[REVIEW' "$GOAL_DIR/IMPLEMENTATION.md" || true
    else
        echo "0"
    fi
}

check_cost() {
    if [ "$MAX_COST_USD" = "0" ]; then
        return 0
    fi
    if [ ! -f "$TELEMETRY_FILE" ]; then
        return 0
    fi
    local total
    total=$(jq -s '[.[].total_cost_usd // 0] | add // 0' "$TELEMETRY_FILE" 2>/dev/null || echo "0")
    # Compare using awk since bash can't do floating point
    if awk "BEGIN {exit !($total >= $MAX_COST_USD)}" 2>/dev/null; then
        echo ""
        echo "=== COST LIMIT REACHED ==="
        printf "Cumulative cost: \$%.2f (limit: \$%s)\n" "$total" "$MAX_COST_USD"
        echo "Increase MAX_COST_USD to continue, or review telemetry:"
        echo "  python3 agents/report.py $GOAL_NAME"
        exit 1
    fi
}

should_replan() {
    local builds_since_plan=$1
    local blocked_before=$2
    local blocked_after=$3
    local feedback_before=$4
    local feedback_after=$5
    local questions_before=$6
    local questions_after=$7

    # Threshold reached
    if [ "$builds_since_plan" -ge "$REPLAN_INTERVAL" ]; then
        return 0
    fi
    # Build agent explicitly requested a replan
    if [ -f "$GOAL_DIR/.replan" ]; then
        echo "--- Build agent requested replan: $(cat "$GOAL_DIR/.replan") ---"
        return 0
    fi
    # New blocked task appeared
    if [ "$blocked_after" -gt "$blocked_before" ]; then
        return 0
    fi
    # Human feedback changed
    if [ "$feedback_before" != "$feedback_after" ]; then
        echo "--- Human feedback detected, triggering replan ---"
        return 0
    fi
    # Agent questions answered
    if [ "$questions_before" != "$questions_after" ]; then
        echo "--- Agent questions answered, triggering replan ---"
        return 0
    fi
    return 1
}

# ── Prompt construction ──────────────────────────────────────────────

build_prompt() {
    local template_file="$1"
    local prompt

    # Multi-variable substitution
    prompt=$(sed \
        -e "s|{GOAL_DIR}|$CONTAINER_GOAL_DIR|g" \
        -e "s|{REPO_NAME}|$REPO_NAME|g" \
        -e "s|{WORKSPACE_DIR}|$CONTAINER_WORKSPACE|g" \
        "$template_file")

    # Append repo CLAUDE.md as context layer if it exists
    local repo_claude_md="$WORKSPACE_DIR/CLAUDE.md"
    if [ "${KEYWORK_SANDBOX:-}" = "1" ]; then
        repo_claude_md="/workspace/CLAUDE.md"
    fi
    if [ -f "$repo_claude_md" ]; then
        prompt="$prompt

---
## Repository Instructions (from CLAUDE.md)

$(cat "$repo_claude_md")"
    fi

    # Append repo knowledge.md as context layer if it exists
    local knowledge_md="agents/repos/$REPO_NAME/knowledge.md"
    if [ "${KEYWORK_SANDBOX:-}" = "1" ]; then
        knowledge_md="/agents/repos/$REPO_NAME/knowledge.md"
    fi
    if [ -f "$knowledge_md" ]; then
        prompt="$prompt

---
## Repository Knowledge

$(cat "$knowledge_md")"
    fi

    # Append check commands as context
    local checks_section=""
    [ -n "$CHECK_LINT" ] && checks_section="${checks_section}
- Lint: \`$CHECK_LINT\`"
    [ -n "$CHECK_TEST" ] && checks_section="${checks_section}
- Test: \`$CHECK_TEST\`"
    [ -n "$CHECK_TYPECHECK" ] && checks_section="${checks_section}
- Typecheck: \`$CHECK_TYPECHECK\`"
    [ -n "$CHECK_BUILD" ] && checks_section="${checks_section}
- Build: \`$CHECK_BUILD\`"

    if [ -n "$checks_section" ]; then
        prompt="$prompt

---
## Check Commands
$checks_section"
    fi

    echo "$prompt"
}

# ── Phase runners ────────────────────────────────────────────────────

run_plan() {
    echo "--- Planning ---"
    local prompt
    prompt=$(build_prompt agents/prompts/plan.md)
    run_agent "plan" "$prompt"
}

run_build() {
    echo "--- Building ---"
    local prompt
    prompt=$(build_prompt agents/prompts/build.md)
    run_agent "build" "$prompt"
}

run_final_gate() {
    echo "--- Final gate ---"
    local prompt
    prompt=$(build_prompt agents/prompts/final_gate.md)
    run_agent "final_gate" "$prompt"
}

# ── Dual commit: commit state changes to keywork repo ────────────────

commit_state_if_changed() {
    local phase="${1:-build}"
    local state_after
    state_after=$(state_checksum)

    if [ "$state_after" != "$STATE_CHECKSUM_BEFORE" ]; then
        # Only commit in non-sandbox mode (host-side)
        if [ "${KEYWORK_SANDBOX:-}" != "1" ]; then
            git add "agents/goals/$GOAL_NAME/" 2>/dev/null || true
            git commit -m "State: $phase for $GOAL_NAME" --no-verify 2>/dev/null || true
        fi
        STATE_CHECKSUM_BEFORE="$state_after"
    fi
}

# ── Stop / pause checks ─────────────────────────────────────────────

check_stop() {
    if [ -f "$GOAL_DIR/.stop" ]; then
        echo ""
        echo "=== STOPPED (found $GOAL_DIR/.stop) ==="
        local reason
        reason=$(cat "$GOAL_DIR/.stop" 2>/dev/null || true)
        [ -n "$reason" ] && echo "Reason: $reason"
        rm -f "$GOAL_DIR/.stop"
        exit 1
    fi
}

check_pause() {
    if [ -f "$GOAL_DIR/.pause" ]; then
        echo ""
        echo "=== PAUSED for human testing ==="
        echo "To provide feedback and resume:"
        echo "  1. Test the application"
        echo "  2. bash agents/feedback.sh $GOAL_NAME"
        echo "  3. bash agents/feedback.sh $GOAL_NAME --resume"
        echo ""
        echo "Or remove the pause manually: rm $GOAL_DIR/.pause"
        echo "Waiting..."
        while [ -f "$GOAL_DIR/.pause" ]; do
            # Also check for stop while paused
            if [ -f "$GOAL_DIR/.stop" ]; then
                check_stop
            fi
            sleep 5
        done
        echo "=== RESUMED ==="
        # After resuming, replan if feedback or questions changed
        FEEDBACK_NOW=$(feedback_checksum)
        QUESTIONS_NOW=$(questions_checksum)
        if [ "$FEEDBACK_NOW" != "$LAST_FEEDBACK_CHECKSUM" ] || [ "$QUESTIONS_NOW" != "$LAST_QUESTIONS_CHECKSUM" ]; then
            if [ "$FEEDBACK_NOW" != "$LAST_FEEDBACK_CHECKSUM" ]; then
                echo "--- Human feedback detected, triggering replan ---"
            fi
            if [ "$QUESTIONS_NOW" != "$LAST_QUESTIONS_CHECKSUM" ]; then
                echo "--- Agent questions answered, triggering replan ---"
            fi
            run_plan
            BUILDS_SINCE_PLAN=0
            LAST_FEEDBACK_CHECKSUM="$FEEDBACK_NOW"
            LAST_QUESTIONS_CHECKSUM="$QUESTIONS_NOW"
            check_exit_conditions
        fi
    fi
}

check_exit_conditions() {
    if [ ! -f "$GOAL_DIR/IMPLEMENTATION.md" ]; then
        echo "No IMPLEMENTATION.md found. Exiting."
        exit 1
    fi

    if ! grep -q '^\- \[ \]' "$GOAL_DIR/IMPLEMENTATION.md" 2>/dev/null; then
        # All tasks are [x] or [BLOCKED]. Run final gate before exiting.
        if [ "${FINAL_GATE_DONE:-0}" -eq 1 ]; then
            echo ""
            echo "All tasks complete! (verified by final gate)"
            echo ""
            echo "If something isn't right after testing:"
            echo "  1. bash agents/feedback.sh $GOAL_NAME"
            echo "  2. bash agents/loop.sh $GOAL_NAME"
            exit 0
        fi
        echo ""
        echo "--- All tasks appear complete. Running final gate... ---"
        FINAL_GATE_DONE=1
        run_final_gate
        commit_state_if_changed "final_gate"
        check_stop
        run_plan
        commit_state_if_changed "plan"
        check_stop
        BUILDS_SINCE_PLAN=0
        LAST_FEEDBACK_CHECKSUM=$(feedback_checksum)
        LAST_QUESTIONS_CHECKSUM=$(questions_checksum)
        rm -f "$GOAL_DIR/.replan"
        # If plan created remediation tasks, continue building
        if grep -q '^\- \[ \]' "$GOAL_DIR/IMPLEMENTATION.md" 2>/dev/null; then
            echo "--- Final gate found issues. Continuing... ---"
            FINAL_GATE_DONE=0
            return 0
        fi
        # No new tasks after final gate — goal is truly complete
        echo ""
        echo "All tasks complete! (verified by final gate)"
        echo ""
        echo "If something isn't right after testing:"
        echo "  1. bash agents/feedback.sh $GOAL_NAME"
        echo "  2. bash agents/loop.sh $GOAL_NAME"
        exit 0
    fi

    local uncompleted unblocked
    uncompleted=$(grep '^\- \[ \]' "$GOAL_DIR/IMPLEMENTATION.md" || true)
    unblocked=$(echo "$uncompleted" | grep -v 'BLOCKED' || true)
    if [ -z "$unblocked" ]; then
        echo "All remaining tasks are BLOCKED. Human intervention needed."
        exit 1
    fi
}

# ── Signal handling ───────────────────────────────────────────────────
trap 'echo ""; echo "=== Interrupted (signal received) ==="; exit 130' INT TERM

# ── Loop ──────────────────────────────────────────────────────────────

echo "Goal:       $GOAL_NAME"
echo "Repo:       $REPO_NAME"
echo "Workspace:  $CONTAINER_WORKSPACE"
echo "Kill switch: echo 'reason' > $GOAL_DIR/.stop"
echo "Pause:       touch $GOAL_DIR/.pause"
echo ""

# Manual override mode — run the specified phase N times, skip auto-selection
if [ -n "$FORCED_PHASE" ]; then
    for ((i = 1; i <= MAX_ITERATIONS; i++)); do
        check_stop
        echo "=== $FORCED_PHASE $i / $MAX_ITERATIONS ==="
        "run_$FORCED_PHASE"
    done
    exit 0
fi

BUILD_COUNT=0
BUILDS_SINCE_PLAN=0
CONSECUTIVE_NOOPS=0
FINAL_GATE_DONE=0
LAST_FEEDBACK_CHECKSUM=$(feedback_checksum)
LAST_QUESTIONS_CHECKSUM=$(questions_checksum)
STATE_CHECKSUM_BEFORE=$(state_checksum)

# Initial plan
run_plan
commit_state_if_changed "plan"
check_stop
check_exit_conditions

while [ $BUILD_COUNT -lt $MAX_ITERATIONS ]; do
    BUILD_COUNT=$((BUILD_COUNT + 1))

    # ── Stop / pause check ─────────────────────────────────────
    check_stop
    check_pause

    echo "=== Build $BUILD_COUNT / $MAX_ITERATIONS (since plan: $((BUILDS_SINCE_PLAN + 1))) ==="

    # Snapshot state before build
    BLOCKED_BEFORE=$(count_blocked_tasks)
    FEEDBACK_BEFORE=$(feedback_checksum)
    QUESTIONS_BEFORE=$(questions_checksum)
    IMPL_BEFORE=$(impl_checksum)

    # Build
    run_build
    BUILDS_SINCE_PLAN=$((BUILDS_SINCE_PLAN + 1))
    commit_state_if_changed "build"
    check_stop
    check_cost

    # Snapshot state after build
    BLOCKED_AFTER=$(count_blocked_tasks)
    FEEDBACK_AFTER=$(feedback_checksum)
    QUESTIONS_AFTER=$(questions_checksum)

    # No-op detection: build didn't change IMPLEMENTATION.md
    IMPL_AFTER=$(impl_checksum)
    if [ "$IMPL_BEFORE" = "$IMPL_AFTER" ]; then
        CONSECUTIVE_NOOPS=$((CONSECUTIVE_NOOPS + 1))
        echo "--- Warning: Build did not change IMPLEMENTATION.md (no-op $CONSECUTIVE_NOOPS) ---"
        if [ "$CONSECUTIVE_NOOPS" -ge 3 ]; then
            echo "ERROR: 3 consecutive no-op builds. Build agent is stuck."
            echo "Remaining tasks in IMPLEMENTATION.md need human review."
            exit 1
        elif [ "$CONSECUTIVE_NOOPS" -ge 2 ]; then
            echo "--- Forcing replan after 2 consecutive no-ops ---"
            run_plan
            commit_state_if_changed "plan"
            check_stop
            BUILDS_SINCE_PLAN=0
            LAST_FEEDBACK_CHECKSUM=$(feedback_checksum)
            rm -f "$GOAL_DIR/.replan"
        fi
    else
        CONSECUTIVE_NOOPS=0
    fi

    # Check if we're done after build
    check_exit_conditions

    # Decide: replan or continue building
    if should_replan "$BUILDS_SINCE_PLAN" "$BLOCKED_BEFORE" "$BLOCKED_AFTER" "$FEEDBACK_BEFORE" "$FEEDBACK_AFTER" "$QUESTIONS_BEFORE" "$QUESTIONS_AFTER"; then
        run_plan
        commit_state_if_changed "plan"
        check_stop
        check_cost
        BUILDS_SINCE_PLAN=0
        LAST_FEEDBACK_CHECKSUM=$(feedback_checksum)
        LAST_QUESTIONS_CHECKSUM=$(questions_checksum)
        rm -f "$GOAL_DIR/.replan"
    fi

    # Re-check after any replanning
    check_exit_conditions
done

echo "Reached max iterations ($MAX_ITERATIONS)"
exit 1
