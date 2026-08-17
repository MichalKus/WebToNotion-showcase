# Deployment

Two environments share one VPS, isolated by port, container name, directory, and volume.

| | Production | Development |
|---|---|---|
| Trigger | Push to `master` | PR opened/updated against `master`, or manual dispatch |
| Port | `8000` | `8001` |
| Docker tag | `vX.Y.Z` + `prod` | `dev` |
| Container | `webtonotion-prod` | `webtonotion-dev` |
| Directory | `/apps/prod/webtonotion` | `/apps/dev/webtonotion` |
| Volume | `webtonotion_webtonotion_cache` | `webtonotion-dev_cache` |

**Pushing a feature branch does not deploy.** It is a private checkpoint. Opening or
updating a PR against `master` is what claims the dev VPS.

The dev environment is a single shared slot — one PR occupies it at a time. Concurrency is
keyed to the target environment rather than the git ref, so a newer dev run **cancels** an
older one, while production runs queue instead of cancelling.

To preview a branch without opening a PR:

```bash
gh workflow run deploy.yml --ref feature/your-branch
```

## Pipeline

`.github/workflows/deploy.yml`, five jobs.

```
setup ─┬─────────────────┐
       │                 ▼
test ──┴──► build-and-push ──► deploy ──► tag-release (prod only)
```

### `setup`

Resolves every environment-dependent value once — `is_prod`, deploy path, port, compose
project, cache volume, GitHub environment — and exposes them as job outputs. Downstream
jobs read those outputs instead of re-evaluating ref conditions.

### `test`

Calls `.github/workflows/python-tests.yml` via `workflow_call`. Installs with
`pip install -e ".[test]"` on Python 3.12 and runs:

```bash
pytest tests/unit/ -v --tb=short
```

**No image is built if unit tests fail.** Integration tests are not run in CI — they hit
live external endpoints. Run those locally.

`python-tests.yml` has no push or pull_request trigger of its own; a standalone trigger
would duplicate every run.

### `build-and-push`

1. Parse `version` from `pyproject.toml`; hard-fail if unparseable.
2. Build locally as `webtonotion:scan-target` (`load: true`, no push) so the scanner has a
   real image to inspect.
3. **Production only:** Trivy scans for CRITICAL/HIGH. The step sets `exit-code: 1` but also
   `continue-on-error: true`, so **findings are uploaded as a SARIF artifact and do not
   block the deploy**.
4. Push. Production gets `vX.Y.Z` and `prod`; development gets `dev`.
5. Emit the image **digest** as a job output.

Layer cache is stored in GitHub Actions cache (`type=gha`), shared across runs.

Docker Hub therefore holds only `dev`, `prod`, and one tag per release — there are no
per-branch tags to clean up.

### `deploy`

Runs under the `production` or `development` GitHub environment, so environment protection
rules and scoped secrets apply.

1. **Pin the image by digest** — `<user>/webtonotion@sha256:...`, not by tag. The job fails
   if no digest was produced. This guarantees the VPS runs the exact image that was tested
   and scanned, even if a floating tag moves underneath it.
2. `scripts/generate_env.py` writes `docker/.env` from `.env.example` plus secrets.
3. SCP `docker/docker-compose.yaml`, `docker/.env`, and `scripts/deploy_remote.sh` to the
   target directory.
4. SSH in, `chmod +x`, and run `deploy_remote.sh`.

### `tag-release`

Production only, and only **after the deploy succeeds** — so a failed deploy cannot leave a
phantom release tag behind. Skips silently if `v<version>` already exists.

## On the VPS: `deploy_remote.sh`

1. **Secure the config** — `chmod 600 .env` immediately, since it arrives with the CI
   runner's umask.
2. **Lock** — `flock` on `.deploy.lock` so two runs cannot touch the same directory at once.
3. **Read config without sourcing** — values are grepped out of `.env` rather than
   `source`d. The file holds live API keys, and sourcing would execute any value containing
   command substitution.
4. **Bootstrap** — create the `app-network` network and the cache volume if missing (both
   are declared `external` in compose, so a clean VPS fails without them). Create an empty
   `cookies.txt` if absent, because Docker would otherwise create a *directory* at that bind
   mount and yt-dlp would silently lose its authentication.
5. **Capture rollback target** (production only) — `docker inspect --format '{{.Image}}'`,
   the immutable image ID. Using `{{.Config.Image}}` would capture the tag, which
   `compose pull` overwrites moments later, making rollback a no-op.
6. **Pull and recreate** — `docker compose pull` then `up -d --force-recreate --no-deps`.
7. **Health check** — polls `http://localhost:<PORT>/api/v1/health/` directly, 30 attempts
   at 2-second intervals (60s ceiling). It polls HTTP rather than Docker's health status,
   which reports `starting` until its first scheduled probe. Aborts early if the container
   stops running. **Runs in both environments**, so a crash-looping dev container is not
   reported as success.
8. **On failure** — dump the last 50 container log lines.
   - **Development:** exit 1. No rollback; a broken dev image stays until the next push.
   - **Production:** rewrite the image pin in `.env` to the captured image ID, recreate, and
     **re-verify health**. The job exits non-zero either way — with a warning if the
     rollback came up healthy, an error if it did not.

## Configuration generation

`scripts/generate_env.py` merges `.env.example` defaults with CI secrets and writes
`docker/.env` at mode 600.

- Every value is **single-quoted**, so a secret containing shell metacharacters cannot be
  misparsed by Compose or executed by anything reading the file. A value containing a
  single quote is rejected rather than mangled — Compose has no escape for it.
- `ALLOWED_HOSTS` is built from the template default, plus the `HOST` secret, plus the
  internal compose service name `webtonotion`, deduplicated in order.
- `ENVIRONMENT` defaults to `production` when not supplied.
- Deployment vars (`WEBTONOTION_IMAGE`, `PORT`, `COMPOSE_PROJECT_NAME`,
  `CACHE_VOLUME_NAME`) are emitted exactly once, from the environment, overriding any
  template default.

## Required secrets

Validated by `generate_env.py` — a missing one fails the deploy before anything is copied:

| Secret | Purpose |
|---|---|
| `NOTION_API_KEY` | Notion integration token |
| `OPENROUTER_API_KEY` | Both AI agents |
| `WHISPER_API_KEY` | Groq transcription |
| `API_KEY` | Value clients send as `X-API-Key` |
| `LOGFIRE_TOKEN` | Observability |
| `HOST` | Domain or IP, merged into `ALLOWED_HOSTS` |

Also needed by the workflow itself:

| Secret | Purpose |
|---|---|
| `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` | Registry auth |
| `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`, `VPS_PORT` | SSH target |

## Docker Compose

`docker/docker-compose.yaml` serves both environments through variable substitution:

```yaml
services:
  webtonotion:
    image: ${WEBTONOTION_IMAGE:-mikus67/webtonotion:prod}
    container_name: ${COMPOSE_PROJECT_NAME:-webtonotion-prod}
    ports:
      - "${PORT:-8000}:8000"
    volumes:
      - webtonotion_cache:/app/cache
      - ./cookies.txt:/app/cookies.txt:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health/"]
    mem_limit: 1536m
    memswap_limit: 1536m
```

The memory cap is sized for a 2 GB VPS: it stops a Whisper or ffmpeg spike from taking the
host down, leaving roughly 512 MB for the OS, reverse proxy, and Docker daemon. Logs rotate
at 10 MB × 3 files so `json-file` cannot fill the disk.

Both the network and the cache volume are declared `external` — `deploy_remote.sh` creates
them if they don't exist.

## Merge gates

| Check | Enforced by |
|---|---|
| Unit tests pass | `python-tests.yml`, via `deploy.yml` |
| `pyproject.toml` version is a semver **increase** over master, and `v<version>` is not already tagged | `pr-check.yml` |
| PR **title** parses as a conventional commit | `commit-lint.yml` |
| `black --check` and `isort --check-only` | `code-quality.yml` |

`flake8` and `mypy` are not wired into CI. Run them locally:

```bash
flake8 src/ tests/ && mypy src/ && pytest
```

## Releasing

1. Bump `version` in `pyproject.toml` — the PR is blocked without it.
2. Open a PR to `master`. This deploys to dev on port 8001 for review.
3. Merge. The push to `master` builds, deploys to prod on port 8000, and — only after the
   deploy is verified healthy — tags `vX.Y.Z`.

## Running locally

```bash
docker build -t webtonotion -f docker/Dockerfile .
```

```bash
docker run -d -p 8000:8000 --env-file .env --name webtonotion webtonotion
```

The image runs Gunicorn with Uvicorn workers (`docker/gunicorn_conf.py`).

## Verifying a deploy

```bash
curl http://<VPS_IP>:8000/api/v1/health/
```

```bash
curl -H "X-API-Key: $API_KEY" http://<VPS_IP>:8000/api/v1/health/status
```

`GET /api/v1/health/notion-health` confirms the Notion token survived `.env` generation —
it returns 401 on a bad token rather than a generic failure.
