FROM python:3.11-slim

# ── System dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        curl \
        ca-certificates \
        gnupg \
        jq \
        build-essential \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 20.x (for Claude CLI) ───────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── uv (Python package manager) ─────────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ── Claude CLI ───────────────────────────────────────────────────────
RUN npm install -g @anthropic-ai/claude-code

# ── Non-root user ───────────────────────────────────────────────────
RUN groupadd --gid 1000 agent \
    && useradd --uid 1000 --gid agent --create-home agent

# ── Writable directories for entrypoint and agent ───────────────────
RUN mkdir -p /home/agent/.claude /home/agent/.cache/uv /home/agent/.ssh \
    && chown -R agent:agent /home/agent

WORKDIR /workspace

# ── Entrypoint ───────────────────────────────────────────────────────
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER agent

ENTRYPOINT ["entrypoint.sh"]
CMD ["bash"]
