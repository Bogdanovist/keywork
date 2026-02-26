#!/bin/bash
set -euo pipefail

# ── Keywork Sandbox Setup ─────────────────────────────────────────
# Validates prerequisites, creates .env, and configures credentials
# for the agent sandbox. Safe to re-run at any time.
#
# Usage: bash agents/sandbox/setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SANDBOX_DIR="$SCRIPT_DIR"
PLATFORM="$(uname)"

PASS=0
WARN=0
FAIL=0
ACTIONS=()

status_ok()   { echo "  [ok] $1"; PASS=$((PASS + 1)); }
status_warn() { echo "  [!!] $1"; WARN=$((WARN + 1)); ACTIONS+=("$2"); }
status_skip() { echo "  [--] $1"; }
status_fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); ACTIONS+=("$2"); }

# ── Prerequisites ───────────────────────────────────────────────────
echo "=== Checking prerequisites ==="
echo ""

# Docker
if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        status_ok "Docker (running)"
    else
        status_fail "Docker installed but daemon not running" \
            "Start Docker Desktop (or OrbStack) and re-run this script"
    fi
else
    if [ "$PLATFORM" = "Darwin" ]; then
        hint="Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    else
        hint="Install Docker Engine: https://docs.docker.com/engine/install/"
    fi
    status_fail "Docker not found" "$hint"
fi

# Claude CLI
if command -v claude >/dev/null 2>&1; then
    status_ok "Claude CLI"
else
    status_fail "Claude CLI not found" "Install: npm install -g @anthropic-ai/claude-code"
fi

# jq
if command -v jq >/dev/null 2>&1; then
    status_ok "jq"
else
    if [ "$PLATFORM" = "Darwin" ]; then
        hint="Install: brew install jq"
    else
        hint="Install: sudo apt-get install jq"
    fi
    status_fail "jq not found" "$hint"
fi

# SSH agent
if [ -n "${SSH_AUTH_SOCK:-}" ] && ssh-add -l >/dev/null 2>&1; then
    KEY_COUNT=$(ssh-add -l | wc -l | tr -d ' ')
    status_ok "SSH agent ($KEY_COUNT key(s) loaded)"
else
    status_warn "SSH agent — no keys loaded" \
        "Load your SSH key: ssh-add ~/.ssh/id_ed25519"
fi

echo ""

# Exit early if critical prereqs missing
if [ $FAIL -gt 0 ]; then
    echo "Critical prerequisites missing. Fix the items above and re-run."
    echo ""
    echo "Action needed:"
    for i in "${!ACTIONS[@]}"; do
        echo "  $((i + 1)). ${ACTIONS[$i]}"
    done
    exit 1
fi

# ── Environment file ───────────────────────────────────────────────
echo "=== Environment configuration ==="
echo ""

ENV_FILE="$SANDBOX_DIR/.env"
ENV_EXAMPLE="$SANDBOX_DIR/.env.example"

if [ ! -f "$ENV_EXAMPLE" ]; then
    echo "ERROR: .env.example not found at $ENV_EXAMPLE"
    exit 1
fi

CREATE_ENV=0
if [ -f "$ENV_FILE" ]; then
    echo "Existing .env found at $ENV_FILE"
    read -p "  Overwrite / Edit / Keep? [o/e/K] " -n 1 -r
    echo ""
    case "${REPLY:-k}" in
        [oO])
            CREATE_ENV=1
            ;;
        [eE])
            "${EDITOR:-${VISUAL:-vi}}" "$ENV_FILE"
            ;;
        *)
            echo "  Keeping existing .env"
            ;;
    esac
else
    CREATE_ENV=1
fi

if [ "$CREATE_ENV" -eq 1 ]; then
    echo "Creating .env — enter values for required variables."
    echo "Press Enter to accept defaults shown in [brackets]."
    echo ""

    DEFAULT_GIT_NAME=$(git config user.name 2>/dev/null || echo "")
    DEFAULT_GIT_EMAIL=$(git config user.email 2>/dev/null || echo "")

    read -rp "  Git user name [$DEFAULT_GIT_NAME]: " INPUT_GIT_NAME
    read -rp "  Git user email [$DEFAULT_GIT_EMAIL]: " INPUT_GIT_EMAIL

    INPUT_GIT_NAME="${INPUT_GIT_NAME:-$DEFAULT_GIT_NAME}"
    INPUT_GIT_EMAIL="${INPUT_GIT_EMAIL:-$DEFAULT_GIT_EMAIL}"

    if [ -z "$INPUT_GIT_NAME" ] || [ -z "$INPUT_GIT_EMAIL" ]; then
        echo ""
        echo "  ERROR: Git user name and email are required."
        exit 1
    fi

    sed \
        -e "s|^GIT_USER_NAME=.*|GIT_USER_NAME=$INPUT_GIT_NAME|" \
        -e "s|^GIT_USER_EMAIL=.*|GIT_USER_EMAIL=$INPUT_GIT_EMAIL|" \
        "$ENV_EXAMPLE" > "$ENV_FILE"

    echo ""
    echo "  .env created at $ENV_FILE"
fi

# Source .env for subsequent validation steps
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

status_ok ".env configured"

# ── Claude credentials ────────────────────────────────────────────
echo ""
echo "=== Claude CLI credentials ==="
echo ""

CLAUDE_CREDS_FOUND=0
CLAUDE_DIR="$HOME/.claude"

if [ "$PLATFORM" = "Darwin" ]; then
    if security find-generic-password -s "Claude Code-credentials" -w >/dev/null 2>&1; then
        CLAUDE_CREDS_FOUND=1
    fi
fi

if [ -f "$CLAUDE_DIR/.credentials.json" ]; then
    CLAUDE_CREDS_FOUND=1
fi

if [ $CLAUDE_CREDS_FOUND -eq 1 ]; then
    if [ -f "$CLAUDE_DIR/.credentials.json" ] && command -v jq >/dev/null 2>&1; then
        expires_at=$(jq -r '.claudeAiOauth.expiresAt // empty' \
            "$CLAUDE_DIR/.credentials.json" 2>/dev/null || true)
        if [ -n "$expires_at" ]; then
            now_ms=$(python3 -c "import time; print(int(time.time() * 1000))")
            if [ "$expires_at" -le "$now_ms" ] 2>/dev/null; then
                status_warn "Claude credentials expired" \
                    "Run 'claude' to re-authenticate"
            else
                remaining_min=$(( (expires_at - now_ms) / 60000 ))
                status_ok "Claude credentials valid (~${remaining_min} min remaining)"
            fi
        else
            status_ok "Claude credentials found"
        fi
    else
        status_ok "Claude credentials found"
    fi
else
    echo "  Claude credentials not found."
    read -p "  Run 'claude' to authenticate now? [Y/n] " -n 1 -r
    echo ""
    if [[ "${REPLY:-y}" =~ ^[Yy]$ ]]; then
        claude || true
        if [ "$PLATFORM" = "Darwin" ]; then
            if security find-generic-password -s "Claude Code-credentials" -w \
                >/dev/null 2>&1; then
                status_ok "Claude credentials configured"
            else
                status_warn "Claude credentials not detected after auth" \
                    "Run 'claude' and complete the authentication flow"
            fi
        elif [ -f "$CLAUDE_DIR/.credentials.json" ]; then
            status_ok "Claude credentials configured"
        else
            status_warn "Claude credentials not detected after auth" \
                "Run 'claude' and complete the authentication flow"
        fi
    else
        status_warn "Claude credentials not configured" \
            "Run 'claude' to authenticate"
    fi
fi

# ── Docker image build ────────────────────────────────────────────
echo ""
echo "=== Docker image ==="
echo ""

read -p "Build the sandbox Docker image now? (may take a few minutes on first run) [Y/n] " -n 1 -r
echo ""
if [[ "${REPLY:-y}" =~ ^[Yy]$ ]]; then
    echo ""
    if docker build -t keywork-sandbox -f "$SANDBOX_DIR/Dockerfile" "$SANDBOX_DIR"; then
        echo ""
        status_ok "Sandbox image built"
    else
        echo ""
        status_fail "Docker image build failed" \
            "Check the Docker build output above for errors"
    fi
else
    status_skip "Docker image build (skipped)"
fi

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "==========================================="
echo "  Keywork Sandbox Setup Summary"
echo "==========================================="
echo ""
echo "  Passed: $PASS   Warnings: $WARN   Failed: $FAIL"

if [ ${#ACTIONS[@]} -gt 0 ]; then
    echo ""
    echo "Action needed:"
    for i in "${!ACTIONS[@]}"; do
        echo "  $((i + 1)). ${ACTIONS[$i]}"
    done
fi

if [ $FAIL -eq 0 ] && [ $WARN -eq 0 ]; then
    echo ""
    echo "All checks passed! Register a repo with:"
    echo "  bash agents/repo_init.sh <repo-name> <git-remote-url>"
elif [ $FAIL -eq 0 ]; then
    echo ""
    echo "Setup mostly complete. Address warnings above when ready."
    echo "You can register a repo with:"
    echo "  bash agents/repo_init.sh <repo-name> <git-remote-url>"
fi
echo ""
