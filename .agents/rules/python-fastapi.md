---
trigger: glob
globs: src/**/*.py, tests/**/*.py
description: Python 3.12 + FastAPI conventions for this repository — layering, typing, async, errors, and tooling.
---

# Python & FastAPI conventions

Applies to everything under `src/webtonotion/` and `tests/`.

## Layering

Dependency flow is one-directional and non-negotiable:

    api  →  services  →  models & config

- `services/` and `models/` must never import from `api/` or `main.py`.
- Models live in `src/webtonotion/models/`. Never define a Pydantic model inline in a
  service — import it (`from webtonotion.models.notion import NotionPagePayload`).
- Before adding a model class, check it does not already exist in `models/`.
- Business logic belongs in `services/`, grouped by concern
  (`extraction/`, `analysis/`, `storage/`); shared helpers in `utils/`.

## Typing

- mypy runs with `disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`,
  `warn_unreachable`, `strict_equality`. Annotate every argument and return type, including
  `-> None`.
- Third-party stubs are waived only for the modules listed under `[[tool.mypy.overrides]]`
  in `pyproject.toml`. Do not add `# type: ignore` to dodge a fixable error.

## Async

Never run blocking I/O or CPU-bound work directly in an `async def` — it stalls the event
loop. yt-dlp, ffmpeg, file reads, and subprocesses all count.

```python
# WRONG
info = ydl.extract_info(url, download=False)

# CORRECT
info = await asyncio.to_thread(ydl.extract_info, url, download=False)
```

## FastAPI

- Routers live in `api/`, one module per concern, mounted in `main.py`.
- Cross-cutting dependencies (`verify_api_key`, rate limiting) are registered **on the
  router in `main.py`**, not repeated per endpoint.
- Auth is an `X-API-Key` header compared in constant time — see `dependencies.py`. There is
  no OAuth/JWT layer and no user model; do not add one unasked.
- Rate limiting is `utils/rate_limiter.py`, per IP. Do not pull in `fastapi-limiter`.
- Settings come from `config/settings.py` (pydantic-settings, `lru_cache`d provider in
  `dependencies.py`). Never read `os.environ` directly in a service.
- Request/response bodies are Pydantic models with `Field(..., description=...)`. Required
  fields stay required — an API response model that mirrors an external contract (Notion
  always returns `id`, `url`, timestamps) should not make those `Optional`.

## Errors

- Raise the domain exceptions in `exceptions.py` (`VideoScrapingError`,
  `NotionAuthenticationError`, `NotionAPIError`, `WebToNotionError`).
- Translation to HTTP status codes happens in one place, `api/process.py`. Services raise;
  they do not build `HTTPException`s.
- Middleware in `api/middleware.py` handles security headers, request logging, content
  length, and unhandled errors.

## Docstrings & comments

- Google-style docstrings on public functions, classes, and modules. Not JSDoc.
- English for all code, comments, docstrings, and log messages.

## Tooling

```bash
pip install -e .[dev]        # setuptools + pyproject; there is no Poetry lockfile
black src/ tests/            # line-length 100
isort src/ tests/            # profile = black
flake8 src/ tests/
mypy src/
pytest                       # asyncio_mode = auto; no @pytest.mark.asyncio needed
```

After implementing a feature or fix, run **only `pytest`** to verify the change. Do not run
`black`, `isort`, `flake8`, or `mypy` unless the user explicitly asks for it — save them for
the pre-PR checklist in [pull-requests.md](pull-requests.md), or whenever specifically
requested.

CI (`code-quality.yml`) currently enforces **only** `black --check` and `isort --check-only`.
flake8 and mypy are not wired in yet, so a green CI run does not mean the types are clean —
run them yourself before pushing when asked to.

## Tests

- `tests/unit/` is mocked and must run offline. `tests/integration/` hits live endpoints.
- `tests/conftest.py` auto-marks tests `integration` / `slow` / `requires_api_keys` /
  `requires_internet` from their path and name — you rarely need to add markers by hand.
- Local fast loop: `pytest tests/ -m "not slow and not requires_api_keys"`.
- Never hand-roll a dict that imitates a Notion payload; construct `NotionPagePayload`.

## Secrets

Never commit or hardcode `NOTION_API_KEY`, `OPENROUTER_API_KEY`, or any `.env` file.
`.env` is gitignored and `scripts/generate_env.py` writes deploy secrets into `docker/.env`
— treat both as untouchable in normal work.
