#!/bin/bash
set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────
REPO_NAME="${1:-}"
REMOTE_URL="${2:-}"

if [ -z "$REPO_NAME" ]; then
    echo "Usage: bash agents/repo_init.sh <repo-name> [git-remote-url]"
    echo ""
    echo "Examples:"
    echo "  bash agents/repo_init.sh my-api git@github.com:org/my-api.git"
    echo "  bash agents/repo_init.sh my-api https://github.com/org/my-api.git"
    echo "  bash agents/repo_init.sh my-api    # uses existing workspace/my-api/"
    exit 1
fi

# ── Validate naming ──────────────────────────────────────────────────
if ! echo "$REPO_NAME" | grep -qE '^[a-z][a-z0-9._-]*$'; then
    echo "Error: Repo name must be lowercase with letters, numbers, hyphens, dots, or underscores; must start with a letter."
    exit 1
fi

REPOS_DIR="agents/repos"
REPO_DIR="$REPOS_DIR/$REPO_NAME"
WORKSPACE_DIR="workspace/$REPO_NAME"
TEMPLATE_DIR="$REPOS_DIR/_template"

# ── Clone or validate workspace ──────────────────────────────────────
if [ -n "$REMOTE_URL" ] && [ ! -d "$WORKSPACE_DIR" ]; then
    echo "=== Cloning $REMOTE_URL to $WORKSPACE_DIR ==="
    mkdir -p workspace
    git clone "$REMOTE_URL" "$WORKSPACE_DIR"
    echo "Clone complete."
elif [ -n "$REMOTE_URL" ] && [ -d "$WORKSPACE_DIR" ]; then
    echo "Workspace already exists at $WORKSPACE_DIR — skipping clone."
    echo "Remote URL provided but ignored (workspace already present)."
elif [ -z "$REMOTE_URL" ] && [ ! -d "$WORKSPACE_DIR" ]; then
    echo "Error: No remote URL provided and workspace not found at $WORKSPACE_DIR"
    echo ""
    echo "Either:"
    echo "  1. Provide a remote URL:  bash agents/repo_init.sh $REPO_NAME <git-remote-url>"
    echo "  2. Manually clone/copy to: $WORKSPACE_DIR"
    exit 1
fi

if [ ! -d "$WORKSPACE_DIR" ]; then
    echo "Error: Workspace not found at $WORKSPACE_DIR after setup."
    exit 1
fi

# ── Create repo config from template ─────────────────────────────────
if [ ! -d "$REPO_DIR" ]; then
    if [ ! -d "$TEMPLATE_DIR" ]; then
        echo "Error: Template not found at $TEMPLATE_DIR"
        exit 1
    fi

    echo "=== Creating repo config from template ==="
    cp -r "$TEMPLATE_DIR" "$REPO_DIR"

    # Fill basic config.yaml fields
    CONFIG_FILE="$REPO_DIR/config.yaml"
    if [ -f "$CONFIG_FILE" ]; then
        sed -i '' "s|^name: .*|name: \"$REPO_NAME\"|" "$CONFIG_FILE"
        sed -i '' "s|^remote: .*|remote: \"${REMOTE_URL:-}\"|" "$CONFIG_FILE"
        sed -i '' "s|^path: .*|path: \"$WORKSPACE_DIR\"|" "$CONFIG_FILE"
        sed -i '' "s|^registered: .*|registered: \"$(date +%Y-%m-%d)\"|" "$CONFIG_FILE"
    fi

    echo "Config created at $REPO_DIR/config.yaml"
else
    echo "Repo config already exists at $REPO_DIR — skipping template copy."
fi

# ── Validate workspace is a git repo ─────────────────────────────────
if [ ! -d "$WORKSPACE_DIR/.git" ]; then
    echo "Warning: $WORKSPACE_DIR is not a git repository."
    echo "Agent commit workflows require a git repo."
fi

# ── Launch interactive repo initialization agent ─────────────────────
echo ""
echo "=== Launching repo initialization agent ==="
echo "The agent will explore the codebase and fill in config.yaml and knowledge.md."
echo ""

PROMPT_FILE="agents/prompts/repo_init.md"
if [ -f "$PROMPT_FILE" ]; then
    PROMPT=$(sed \
        -e "s|{REPO_NAME}|$REPO_NAME|g" \
        -e "s|{WORKSPACE_DIR}|$WORKSPACE_DIR|g" \
        "$PROMPT_FILE")

    CLAUDE_ARGS=(--system-prompt "$PROMPT")
    if [ "${KEYWORK_SANDBOX:-}" = "1" ]; then
        CLAUDE_ARGS+=(--dangerously-skip-permissions)
    fi

    claude "${CLAUDE_ARGS[@]}" "Explore the codebase at $WORKSPACE_DIR and fill in the repo configuration and knowledge files."
else
    echo "Warning: No repo_init prompt found at $PROMPT_FILE"
    echo "Skipping interactive initialization. Please fill in config.yaml manually."
fi

echo ""
echo "Repo '$REPO_NAME' initialized."
echo ""
echo "  Config:    $REPO_DIR/config.yaml"
echo "  Knowledge: $REPO_DIR/knowledge.md"
echo "  Workspace: $WORKSPACE_DIR"
echo ""
echo "Next steps:"
echo "  1. Review and edit $REPO_DIR/config.yaml (especially check commands)"
echo "  2. Create a goal: bash agents/new_goal.sh <goal-name> $REPO_NAME"
