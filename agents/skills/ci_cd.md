# Skill: CI/CD

## When to Use

Use this skill for tasks that create or modify CI/CD pipelines, including GitHub Actions workflows, GitLab CI configurations, or similar automation. This covers build pipelines, deployment workflows, automated testing, and release processes.

## Pipeline Stages

Every pipeline follows this order. Each stage must pass before the next runs:

```
lint → test → build → deploy
```

## Workflow File Structure

For GitHub Actions, workflow files live in `.github/workflows/`. For GitLab CI, use `.gitlab-ci.yml`. Name files descriptively:

```
.github/workflows/
├── ci.yml              # Lint, test, build on every push/PR
├── deploy-staging.yml  # Deploy to staging on merge to main
└── deploy-prod.yml     # Deploy to production on release tag
```

## Basic CI Workflow (GitHub Actions)

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4  # adapt to repo language
        with:
          node-version: "20"
          cache: "npm"
      - run: npm ci
      - run: npm run lint

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
      - run: npm ci
      - run: npm test

  build:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
      - run: npm ci
      - run: npm run build
```

Adapt the setup action and commands to the repo's language. Use commands from `agents/repos/{REPO_NAME}/config.yaml` under `checks`.

## Triggers and Concurrency

Common triggers: `push` (branches), `pull_request`, `release` (types: published), `schedule` (cron), `workflow_dispatch` (manual). Always set `concurrency` to cancel redundant runs on the same branch.

## Caching Dependencies

Use built-in caching in setup actions where available:

| Language | Setup action | Cache |
|----------|-------------|-------|
| Node.js | `actions/setup-node@v4` | `cache: "npm"` |
| Python | `actions/setup-python@v5` | `cache: "pip"` |
| Go | `actions/setup-go@v5` | `cache: true` |
| Rust | `actions/cache@v4` | `key: rust-${{ hashFiles('Cargo.lock') }}` |

For Docker builds, use `cache-from: type=gha` and `cache-to: type=gha,mode=max` with `docker/build-push-action`.

## Secrets Management

- Never hardcode secrets in workflow files, scripts, or source code
- Use repository or environment secrets: `${{ secrets.API_KEY }}`
- Document required secrets in workflow comments
- Restrict secret access to specific environments where possible

```yaml
steps:
  - name: Deploy
    env:
      DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}  # Required: service account token
    run: ./deploy.sh
```

## Matrix Builds

Test across multiple versions or platforms when the project supports them:

```yaml
strategy:
  matrix:
    node-version: [18, 20, 22]
    os: [ubuntu-latest, macos-latest]
  fail-fast: false
```

Use `fail-fast: false` to see all failures, not just the first one.

## Deployment Patterns

**Staging** — deploy on merge to main using `on: push: branches: [main]`. Set `environment: staging` on the job.

**Production** — deploy on release using `on: release: types: [published]`. Set `environment: production` and configure environment protection rules in GitHub Settings for manual approval.

**Rollback** — create a `workflow_dispatch` workflow that accepts a version input and redeploys that version.

```yaml
# Production deploy job structure
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://myapp.example.com
    steps:
      - uses: actions/checkout@v4
      - run: ./deploy.sh production
        env:
          DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}
```

## Notifications

Add failure notifications and a CI badge to the README:

```yaml
- name: Notify on failure
  if: failure()
  uses: slackapi/slack-github-action@v1
  with:
    channel-id: "deployments"
    slack-message: "Pipeline failed: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
  env:
    SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

```markdown
![CI](https://github.com/{owner}/{repo}/actions/workflows/ci.yml/badge.svg)
```

## Anti-Patterns

- **Tests that do not fail the pipeline**: Every test command must exit non-zero on failure.
- **Deploying without tests**: Deploy jobs must `needs:` the test job.
- **Hardcoded credentials**: Use `${{ secrets.NAME }}`, never inline values.
- **No caching**: Always cache dependencies to avoid reinstalling from scratch.
- **Missing concurrency control**: Without `concurrency`, redundant runs waste resources.
- **`:latest` tags in CI**: Pin all action and image versions for reproducibility.
- **No artifact retention**: Set `retention-days` on uploaded artifacts.

## Checklist Before Submitting

1. Pipeline stages run in order: lint, test, build, deploy
2. Tests failing causes the pipeline to fail
3. Dependencies are cached
4. All secrets use `${{ secrets.NAME }}`
5. Production deployments require manual approval or release triggers
6. Concurrency is configured to cancel redundant runs
7. Workflow files have descriptive names and comments
