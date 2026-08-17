# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FastAPI application that processes video URLs (YouTube, Vimeo, Facebook, Instagram, TikTok, Twitter/X, etc.), extracts structured content via yt-dlp + Whisper transcription + PydanticAI analysis, and creates organized pages in Notion databases.

## Commands

- Install: `pip install -e .[dev]` (ffmpeg must be on PATH for audio extraction)
- Run dev server: `python -m webtonotion.main`
- Run production: `uvicorn webtonotion.main:create_app --host 0.0.0.0 --port 8000`
- Test all: `pytest`
- Test single: `pytest tests/unit/test_notion_mapper.py -k "test_validate_notion_payload_success"`
- Test unit only: `pytest tests/unit/`
- Test integration only: `pytest tests/integration/` (hits live external endpoints)
- Skip slow/API-key tests: `pytest tests/ -m "not slow and not requires_api_keys"`
- Format checks: `black --check .` and `isort --check-only .`
- Format apply: `black src/ tests/` and `isort src/ tests/`
- Lint: `flake8 src/ tests/`
- Typecheck: `mypy src/`
- Docker build: `docker build -t webtonotion -f docker/Dockerfile .`
- Generate `.env` (used by CI/deploy): `python scripts/generate_env.py`

## Architecture

- `src/webtonotion/api`: FastAPI routers (`process.py`, `health.py`), middleware (security headers, error handling, request logging, content-length).
- `src/webtonotion/config`: `settings.py` (pydantic-settings, loads `.env`) and `logging.py` (structured logging + Logfire setup).
- `src/webtonotion/models`: Pydantic models — `video.py` (`VideoContent`), `notion.py` (Notion payloads/responses), `request.py` (API inputs).
- `src/webtonotion/services`: business logic, organized by concern:
  - `services/extraction/`: `YtDlpExtractor` — primary video metadata/audio extraction.
  - `services/analysis/`: `AudioTranscriber` (Whisper), `ContentAnalyzer` (PydanticAI topic/sentiment/location extraction), `notion_mapper.py` (maps `VideoContent` to Notion database schema/properties).
  - `services/storage/`: `FileCacheService` — caches processed video content to avoid reprocessing.
  - `video_scraping_service.py`: orchestrates the above (extract → transcribe → analyze) into a `VideoContent`.
  - `notion_service.py`: Notion API client wrapper (fetches DB schema, creates pages).
- `src/webtonotion/dependencies.py`: FastAPI DI providers — settings (`lru_cache`d), service constructors, API key auth (`verify_api_key`, constant-time compare via `X-API-Key` header), per-IP rate limiting.
- `src/webtonotion/utils/rate_limiter.py`: `RateLimiter` used by the rate-limit dependency.
- `tests/`: `tests/unit/` (mocked, run locally) vs `tests/integration/` (hit live external endpoints). `tests/conftest.py` auto-tags tests with `integration`/`slow`/`requires_api_keys`/`requires_internet` markers based on path/name.
- Dependency flow is one-directional: `api` → `services` → `models` & `config`. Services/models must never import from `api` or `main.py`.

### Request flow (`POST /api/v1/process/url`)

1. `verify_api_key` + rate-limit dependency run first (registered on the router in `main.py`, not per-endpoint).
2. `_validate_request_and_get_db_schema`: fetches Notion DB schema, confirms URL is a supported video URL.
3. `VideoScrapingService.process_video`: yt-dlp extraction → Whisper transcription → PydanticAI content analysis → `VideoContent`.
4. `NotionService.create_video_page`: maps `VideoContent` onto the target database's schema and creates the page.

Errors are caught by type (`VideoScrapingError`, `NotionAuthenticationError`, `NotionAPIError`, `WebToNotionError`) and translated to specific HTTP status codes in `api/process.py`.

## Code patterns

- Always annotate return and argument types (`mypy` runs with `disallow_untyped_defs`, `disallow_incomplete_defs`, etc. — see `pyproject.toml`).
- Define Pydantic models for PydanticAI agent outputs rather than parsing free text:
  ```python
  from pydantic import BaseModel
  from pydantic_ai import Agent
  class Category(BaseModel):
      name: str
  agent = Agent(model="openai/gpt-4o-mini", output_type=Category)
  ```
- Never run CPU-bound or blocking I/O (yt-dlp, file reading, subprocesses) directly inside an async function — wrap it:
  ```python
  # WRONG: blocks the event loop
  info = ydl.extract_info(url, download=False)
  # CORRECT: runs in a thread pool
  info = await asyncio.to_thread(ydl.extract_info, url, download=False)
  ```

## Boundaries

- Never commit/hardcode secrets (`NOTION_API_KEY`, `OPENROUTER_API_KEY`, etc.) or `.env` files. Read config through `settings.py` only.
- Never modify files in `cache/` or `tmp/` without ensuring automatic cleanup (config `cleanup_temp_files`).
- Do not run VPS deployment scripts (`scripts/deploy_remote.sh`) without explicit user permission — `scripts/generate_env.py` writes deploy secrets into `docker/.env`.
- Do not mock Notion payload structures in tests; use `NotionPagePayload` directly.

## Git / CI

- Commits use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`); `.github/workflows/commit-lint.yml` enforces this on the **PR title** (`amannn/action-semantic-pull-request`), not on individual commits.
- Branch names follow `feature/amazing-feature` format. The repo uses GitHub Flow: `feature/*` branches PR directly into `master`. There is no `develop` branch.
- A version bump in `pyproject.toml` is mandatory on every PR to `master` — every merge is a release. `pr-check.yml` compares against `master`'s version with a semver ordering check.
- `.github/workflows/`: `code-quality.yml` runs `black --check` + `isort --check-only` on every branch push. `python-tests.yml` is a reusable workflow invoked by `deploy.yml`, so **unit tests gate every build**. `deploy.yml` deploys a PR to dev:8001 and a push to `master` to prod:8000, pinned by image digest.
- **Opening a PR deploys to the dev VPS.** Pushing a feature branch on its own does not deploy — only PR open/update, or a manual `workflow_dispatch`.

## Detailed rules

Shared with Antigravity and any AGENTS.md-aware tool. Read the relevant file before working in that area — they are not auto-loaded.

- [.agents/rules/00-project.md](.agents/rules/00-project.md) — repo identity, stack, MCP defaults.
- [.agents/rules/python-fastapi.md](.agents/rules/python-fastapi.md) — layering, typing, async, errors, tooling.
- [.agents/rules/pydantic-ai.md](.agents/rules/pydantic-ai.md) — agent config, validation, testing without a live model.
- [.agents/rules/git-workflow.md](.agents/rules/git-workflow.md) — branches, commits, CI gates, deploy side effects.
- [.agents/rules/pull-requests.md](.agents/rules/pull-requests.md) — PR title, description, pre-merge checklist.
- [.agents/workflows/architecture-plan.md](.agents/workflows/architecture-plan.md) — workflow for planning a feature.

## Docs on demand

Published documentation lives in `docs/` and describes current behaviour. Read the relevant
file before working in that area.

- [docs/architecture.md](docs/architecture.md) — layering, request flow, middleware, error translation.
- [docs/api.md](docs/api.md) — endpoints, request/response shapes, status codes.
- [docs/configuration.md](docs/configuration.md) — every setting, defaults, and known traps.
- [docs/video-processing.md](docs/video-processing.md) — yt-dlp settings, Groq transcription, analysis, caching.
- [docs/notion-integration.md](docs/notion-integration.md) — schema fetch, mapper agent, output validation.
- [docs/deployment.md](docs/deployment.md) — CI/CD pipeline, environments, release process.

`.workbench/` is gitignored local scratch: agent plans, model reviews, research dumps, and
operational runbooks. Write plans and reviews there, never into `docs/`.
