# Skill: Docker

## When to Use

Use this skill for tasks that create or modify Dockerfiles, docker-compose configurations, or container-related infrastructure. This includes containerizing applications, setting up development environments, and configuring multi-service deployments.

## Dockerfile Structure

Use multi-stage builds to separate build-time dependencies from the runtime image:

```dockerfile
# ── Build stage ──────────────────────────────────────
FROM node:20-slim AS builder
WORKDIR /app

# Copy dependency files first (cache layer)
COPY package.json package-lock.json ./
RUN npm ci --production=false

# Copy source and build
COPY src/ src/
COPY tsconfig.json ./
RUN npm run build

# ── Runtime stage ────────────────────────────────────
FROM node:20-slim
WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy only production dependencies and built artifacts
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY package.json ./

# Switch to non-root user
USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

ENTRYPOINT ["node", "dist/server.js"]
```

## Base Images

- Use specific version tags, never `:latest` — pinned versions ensure reproducible builds
- Prefer slim or alpine variants to minimize image size and attack surface
- Common choices:

| Language | Base image |
|----------|-----------|
| Python | `python:3.12-slim` |
| Node.js | `node:20-slim` |
| Go | `golang:1.22-alpine` (build), `gcr.io/distroless/static` (runtime) |
| Rust | `rust:1.77-slim` (build), `debian:bookworm-slim` (runtime) |
| Java | `eclipse-temurin:21-jre-alpine` |

For compiled languages (Go, Rust), the runtime stage can use a minimal base like `distroless` or `alpine` since only the binary is needed.

## Layer Caching

Order Dockerfile instructions from least to most frequently changed:

1. Base image and system packages (rarely changes)
2. Dependency manifest files (`package.json`, `requirements.txt`, `go.mod`)
3. Dependency installation
4. Source code copy
5. Build command

This order ensures that changing source code does not invalidate the dependency cache layer.

## .dockerignore

Always create or update `.dockerignore` in the build context root:

```
.git/
.github/
.vscode/
.idea/
node_modules/
__pycache__/
*.pyc
.env
.env.*
*.log
tests/
docs/
coverage/
.pytest_cache/
.ruff_cache/
target/
dist/
build/
tmp/
```

## Security

- **Run as non-root**: Create a dedicated user and switch with `USER` before the entrypoint
- **No secrets in images**: Pass credentials via environment variables or mounted secrets at runtime
- **Use COPY, not ADD**: `COPY` is explicit; `ADD` has implicit behaviors (tar extraction, URL fetching) that can introduce surprises
- **Minimal packages**: Only install what the application needs — do not include build tools in the runtime stage
- **Read-only filesystem**: Where possible, run with `--read-only` and mount writable volumes only where needed

## Health Checks

Every service must have a `HEALTHCHECK` instruction. Use `curl -f` for HTTP services, `nc -z` for TCP services, or a custom script. If curl is not in the image, install it or use a language-native check.

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

## Docker Compose

For multi-service setups, use Compose with clear service naming and dependency management:

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgres://user:pass@db:5432/myapp
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: myapp
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  db_data:
```

Conventions:
- Service names are lowercase, hyphen-separated (`api-server`, not `ApiServer`)
- Use `depends_on` with health check conditions to control startup order
- Named volumes for persistent data — never bind-mount production data directories
- Document all required environment variables with comments or a `.env.example`

## Environment Variables

- Use `ENV` for non-sensitive defaults (port, log level). Document required runtime variables in comments or `.env.example`.
- Never set secrets via `ENV` or `ARG` — they persist in image layers. Inject at runtime with `-e` flags or secret mounts.

## Anti-Patterns

- **`:latest` tags**: Breaks reproducibility. Always pin versions.
- **Single-stage builds for compiled languages**: Bloats the final image with build tools.
- **Running as root**: Security risk. Always create and switch to a non-root user.
- **Storing secrets in `ENV` or `ARG`**: Visible in image history. Use runtime injection.
- **`ADD` for local files**: Use `COPY`. Reserve `ADD` only for tar extraction if truly needed.
- **Missing `.dockerignore`**: Sends the entire build context to the daemon, including `.git`, `node_modules`, and secrets.
- **Installing dev dependencies in production image**: Increases size and attack surface.
