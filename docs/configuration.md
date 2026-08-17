# Configuration

All settings load from environment variables and `.env` via pydantic-settings
(`src/webtonotion/config/settings.py`). Names are case-insensitive; unknown keys are
ignored rather than rejected.

Start from the template:

```bash
cp .env.example .env
```

## Required

The service will not work without these four:

| Variable | Purpose |
|---|---|
| `NOTION_API_KEY` | Notion integration token. The integration must also be shared with each target database |
| `OPENROUTER_API_KEY` | Content analysis and Notion mapping agents. **Both agents construct at import time — the app fails to start without it** |
| `WHISPER_API_KEY` | Groq API key for transcription |
| `API_KEY` | Value clients send as `X-API-Key`. If unset, every authenticated request returns 500 |

## Notion

| Variable | Default | Notes |
|---|---|---|
| `NOTION_API_KEY` | — | Integration token |
| `NOTION_VERSION` | `2025-09-03` | The schema fetch reads `data_sources`, which older API versions don't return. `.env.example` already sets it correctly; the code default does not |

## AI services

| Variable | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | Used by both agents. Weaker models fail the mapper's output validator more often |
| `WHISPER_API_KEY` | — | Groq key, not OpenAI |
| `WHISPER_MODEL` | `whisper-large-v3` | Groq model name |

## Video extraction

| Variable | Default | Notes |
|---|---|---|
| `MAX_VIDEO_DURATION` | `3600` | Seconds. Longer videos skip audio download and transcription entirely |
| `MAX_FILE_SIZE` | `500MB` | Accepts `500MB`, `1GB`, `1024KB`, or a raw byte count |
| `AUDIO_QUALITY` | `best` | `best` (VBR), `good` (192k), `medium` (128k). Anything else falls back to 192k |
| `COOKIES_FILE_PATH` | unset | Netscape-format cookies for login-gated content. Logs a warning if set but missing |
| `TEMP_DIR` | `/tmp/webtonotion` | Audio working directory. Created at startup |
| `CLEANUP_TEMP_FILES` | `true` | Delete audio after transcription, on success and failure |
| `VERBOSE_LOGGING` | `false` | Passes `verbose` to yt-dlp |

## Caching

| Variable | Default | Notes |
|---|---|---|
| `ENABLE_CACHING` | `true` | Disables both read and write when false |
| `CACHE_DIR` | `./cache` | One JSON file per URL, named by MD5 hash |
| `CACHE_EXPIRATION` | `86400` | Seconds. `0` never expires. Expired files are ignored but not deleted |

## Security and limits

| Variable | Default | Notes |
|---|---|---|
| `API_KEY` | — | Compared with `secrets.compare_digest` |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated. Drives both `TrustedHostMiddleware` and, outside debug, CORS origins |
| `RATE_LIMIT_REQUESTS` | `60` | Per IP per window. `.env.example` ships `100` |
| `RATE_LIMIT_WINDOW` | `60` | Seconds. `.env.example` ships `3600` |
| `MAX_CONTENT_LENGTH` | `104857600` | 100 MB request body ceiling |
| `REQUEST_TIMEOUT` | `300` | Seconds. Applies to the Notion client and yt-dlp sockets |
| `MAX_RETRIES` | `3` | Shared by yt-dlp, Groq, and both PydanticAI agents |

Rate-limit state is a per-process dictionary. With `WORKERS > 1` the effective limit is
multiplied by the worker count.

## Server

| Variable | Default | Notes |
|---|---|---|
| `HOST` | `0.0.0.0` | |
| `PORT` | `8000` | |
| `WORKERS` | `1` | 1–32 |
| `FORWARDED_ALLOW_IPS` | `*` | Proxies trusted for `X-Forwarded-*`. Narrow this in production |
| `DEBUG` | `false` | Enables reload and **opens CORS to `*`** |
| `ENVIRONMENT` | `development` | `development`, `staging`, or `production` |
| `LOG_LEVEL` | `INFO` | |

## Observability

| Variable | Default | Notes |
|---|---|---|
| `LOGFIRE_TOKEN` | unset | Optional. Tracing is disabled without it |
| `LOGFIRE_PROJECT_NAME` | `webtonotion` | |

## Gotchas

- **`DEBUG=true` in production opens CORS to every origin.** Keep it false outside local
  development.
