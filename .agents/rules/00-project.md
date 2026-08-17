---
trigger: always_on
description: Core facts about the WebToNotion repository — identity, stack, and where the detailed rules live.
---

# WebToNotion — project facts

FastAPI service that takes a video URL (YouTube, Vimeo, Facebook, Instagram, TikTok, X, …),
extracts it with yt-dlp, transcribes with Whisper, analyses with PydanticAI, and creates a
page in a Notion database.

## Repository

- Owner: `MichalKus` · Repo: `WebToNotion` · https://github.com/MichalKus/WebToNotion
- Default branch: `master` (GitHub Flow: feature branches PR directly to `master`)
- When calling GitHub MCP tools, default to `owner: "MichalKus"`, `repo: "WebToNotion"`,
  and branch `master` unless the task says otherwise.

## Stack (authoritative list is `pyproject.toml`)

Python 3.12+ · FastAPI · Uvicorn/Gunicorn · Pydantic v2 + pydantic-settings · pydantic-ai
(OpenRouter) · notion-client · yt-dlp · openai (Whisper transcription) · pydub +
ffmpeg-python · httpx · logfire.

**Not in this project** — do not introduce them without being asked: any database, ORM,
SQLAlchemy, Alembic, Poetry, Ruff, Celery, Redis, or a frontend.

## Where the rules are

- `CLAUDE.md` — commands, architecture, code patterns, boundaries. Read it first.
- `.agents/rules/python-fastapi.md` — backend conventions.
- `.agents/rules/pydantic-ai.md` — agent conventions.
- `.agents/rules/git-workflow.md` — branching, commits, CI gates.
- `.agents/rules/pull-requests.md` — PR requirements.
- `.agents/workflows/architecture-plan.md` — on-demand: plan a feature's architecture.
- `docs/` — published documentation of current behaviour; the guides listed in `CLAUDE.md`.
- `.workbench/` — gitignored local scratch: plans, reviews, research, runbooks. Never `docs/`.
