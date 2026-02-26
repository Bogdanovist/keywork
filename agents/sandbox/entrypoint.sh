#!/bin/bash
set -euo pipefail

# ── Claude OAuth tokens ─────────────────────────────────────────────
# Host's ~/.claude is mounted read-only at /home/agent/.claude-host.
# The CLI needs write access to its config dir, so we copy auth files
# to a writable location.
if [ -f /home/agent/.claude-host/.credentials.json ]; then
    cp /home/agent/.claude-host/.credentials.json /home/agent/.claude/.credentials.json
    chmod 600 /home/agent/.claude/.credentials.json
    echo "[sandbox] Claude credentials copied."
else
    echo "[sandbox] WARNING: No Claude credentials found at /home/agent/.claude-host/.credentials.json"
    echo "[sandbox] The Claude CLI will not be authenticated."
fi

if [ -f /home/agent/.claude-host/settings.json ]; then
    cp /home/agent/.claude-host/settings.json /home/agent/.claude/settings.json
fi

# ── Git configuration ────────────────────────────────────────────────
if [ -n "${GIT_USER_NAME:-}" ]; then
    git config --global user.name "$GIT_USER_NAME"
fi
if [ -n "${GIT_USER_EMAIL:-}" ]; then
    git config --global user.email "$GIT_USER_EMAIL"
fi

# Bind-mounted repos may have different ownership — mark as safe
git config --global --add safe.directory /workspace
git config --global --add safe.directory /keywork

# ── SSH agent forwarding ─────────────────────────────────────────────
if [ -n "${SSH_AUTH_SOCK:-}" ]; then
    ssh-keyscan -t ed25519,rsa github.com >> /home/agent/.ssh/known_hosts 2>/dev/null
    ssh-keyscan -t ed25519,rsa gitlab.com >> /home/agent/.ssh/known_hosts 2>/dev/null
    ssh-keyscan -t ed25519,rsa bitbucket.org >> /home/agent/.ssh/known_hosts 2>/dev/null
    chmod 600 /home/agent/.ssh/known_hosts
    echo "[sandbox] SSH agent forwarding configured."
fi

# ── Repo-specific setup commands ─────────────────────────────────────
# Run any setup commands defined in the repo's config.yaml.
# These are passed via KEYWORK_SETUP_COMMANDS env var (newline-separated).
if [ -n "${KEYWORK_SETUP_COMMANDS:-}" ]; then
    echo "[sandbox] Running repo setup commands..."
    cd /workspace
    while IFS= read -r cmd; do
        if [ -n "$cmd" ]; then
            echo "[sandbox]   → $cmd"
            eval "$cmd"
        fi
    done <<< "$KEYWORK_SETUP_COMMANDS"
    echo "[sandbox] Setup commands complete."
fi

# ── Dependency installation ──────────────────────────────────────────
# Auto-detect and install dependencies for common package managers.
cd /workspace
if [ -f pyproject.toml ] && command -v uv &>/dev/null; then
    echo "[sandbox] Installing Python dependencies..."
    uv sync --all-groups 2>/dev/null || uv sync 2>/dev/null || true
    echo "[sandbox] Python dependencies ready."
elif [ -f requirements.txt ]; then
    echo "[sandbox] Installing Python dependencies..."
    pip install -r requirements.txt -q || true
    echo "[sandbox] Python dependencies ready."
fi

if [ -f package.json ] && [ ! -d node_modules ]; then
    echo "[sandbox] Installing Node.js dependencies..."
    if [ -f package-lock.json ]; then
        npm ci --quiet || true
    elif [ -f yarn.lock ]; then
        npx yarn install --frozen-lockfile --quiet 2>/dev/null || true
    else
        npm install --quiet || true
    fi
    echo "[sandbox] Node.js dependencies ready."
fi

# ── Hand off to the command ──────────────────────────────────────────
cd /workspace
echo "[sandbox] Starting: $*"
exec "$@"
