# API Reference

Base URL: `http://localhost:8000` in development. All routes are mounted under `/api/v1`.

Interactive OpenAPI docs are served at `/docs` and `/redoc`.

## Authentication

Every route on the process router requires an `X-API-Key` header matching the server's
`API_KEY` setting:

```bash
curl -H "X-API-Key: $API_KEY" ...
```

If `API_KEY` is not configured on the server, the API fails closed and returns
`500 Server API key configuration is missing` for every authenticated request.

Health endpoints are open, except `/health/status`.

Requests are rate limited per client IP using `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW`.

## `POST /api/v1/process/url`

Extract a video, analyse it, and create a page in the target Notion database.

### Request

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "database_id": "12345678-1234-1234-1234-123456789012"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `url` | string | yes | Must be a valid HTTP/HTTPS URL on a [supported platform](video-processing.md#supported-platforms) |
| `database_id` | string | yes in practice | Optional in the model, but the endpoint returns 400 without it |

The Notion integration must be shared with the target database, or the schema fetch fails
with 401.

### Response — 200

```json
{
  "success": true,
  "message": "Video URL processed and Notion page created successfully",
  "page_id": "1a2b3c4d-...",
  "page_url": "https://www.notion.so/...",
  "content_type": "video",
  "video_details": {
    "title": "How to Make Perfect Pasta",
    "duration": 480.0,
    "author": "Chef Mario",
    "topics": ["cooking", "italian cuisine", "pasta"],
    "sentiment": "positive",
    "locations": ["Bologna", "Italy"],
    "transcript_length": 1500,
    "metadata": {
      "platform": "youtube",
      "view_count": 125000,
      "like_count": 3500,
      "video_id": "dQw4w9WgXcQ",
      "key_insights": "[\"Salt the water heavily\", \"Finish pasta in the sauce\"]",
      "content_category": "tutorial"
    }
  },
  "processing_stats": {
    "transcription_available": true,
    "ai_analysis_completed": true,
    "cache_hit": false
  }
}
```

Notes on specific fields:

- `duration` is a float in seconds, or `null` when the platform doesn't report one.
- `transcript_length` is the character count, not a word count. It is `0` when
  transcription was skipped or failed.
- `metadata.key_insights` is a **JSON-encoded string**, not an array.
- `metadata.skipped_transcription` is present with value `"duration_exceeded"` when the
  video was longer than `MAX_VIDEO_DURATION`.
- `processing_stats.cache_hit` is currently always `false` — the flag is not yet wired to
  the cache lookup.

### Errors

| Status | Condition |
|---|---|
| 400 | `database_id` missing, or the URL is not a supported video URL |
| 401 | Missing or invalid `X-API-Key`, or Notion authentication failed |
| 422 | Request body failed validation, or extraction/transcription failed (`VideoScrapingError`) |
| 500 | Server `API_KEY` not configured, or an unexpected error |
| 503 | Notion API returned an error |

Error bodies follow FastAPI's shape: `{"detail": "..."}`. Unexpected 500s return a generic
message; the specific error is logged server-side with the request ID.

### Example

```bash
curl -X POST "http://localhost:8000/api/v1/process/url" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","database_id":"YOUR_DB_ID"}'
```

## `GET /api/v1/process/status`

Reports which capabilities are available. Requires `X-API-Key`.

```json
{
  "video_scraping": "available",
  "web_scraping": "not_implemented",
  "notion_integration": "available",
  "ai_agents": "available",
  "supported_video_platforms": [
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv"
  ]
}
```

The `supported_video_platforms` list here is hardcoded in the endpoint and is **narrower
than what the service actually accepts** — see
[the full list](video-processing.md#supported-platforms).

## `POST /api/v1/chat`

Run one turn of the agentic orchestrator. The agent may call read-only tools
(`find_databases`, `inspect_schema`) and, once a database is confirmed for the
session, `save_to_notion` — a write attempted before confirmation is refused by
the tool itself, not by the prompt. Requires `X-API-Key`.

The video tools (`get_video_metadata`, `get_transcript`, `summarize`,
`ask_about_video`) and the mapper-backed write are not implemented yet; a
confirmed `save_to_notion` call currently returns a placeholder result. See
[the design spec](superpowers/specs/2026-08-17-agentic-orchestrator-design.md)
for the full tool belt this surface is built towards.

### Request

```json
{
  "message": "find me a database to save videos to",
  "conversation_id": "c1",
  "session_id": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `message` | string | yes | Non-empty user message |
| `conversation_id` | string | yes | Groups messages of one conversation |
| `session_id` | string \| null | no | Omit to start a new session; pass an existing one to continue it |

### Response — 200

```json
{
  "session_id": "3f9c2e7a1b4d4f6e8a0c2d5e7f9a1b3c",
  "reply": "I found a few candidates: \"Watch Later\" and \"Reading List\". Which one?",
  "confirmed_database_id": null
}
```

`confirmed_database_id` is `null` until a `confirm_database` tool call has run in
this session; once set, it stays set for the rest of the session unless the user
corrects it.

### Errors

| Status | Condition |
|---|---|
| 401 | Missing or invalid `X-API-Key`, or Notion authentication failed |
| 404 | `session_id` was supplied but does not exist |
| 409 | A second message raced this session's write (two concurrent turns on one `session_id`) |
| 422 | Request body failed validation |
| 500 | Server `API_KEY` not configured, or an unexpected error |
| 503 | Notion API returned an error |

### Example

```bash
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"message":"find me a database to save videos to","conversation_id":"c1"}'
```

## `GET /api/v1/chat/{session_id}`

Replay a session's full message history (Pydantic AI's own serialized message
objects — requests, responses, tool calls, and tool returns) for a UI to render.
Requires `X-API-Key`. Returns 404 if the session does not exist.

```json
{
  "session_id": "3f9c2e7a1b4d4f6e8a0c2d5e7f9a1b3c",
  "messages": [ ... ]
}
```

## `DELETE /api/v1/chat/{session_id}`

Delete a session and its message history. Idempotent — deleting an unknown or
already-deleted `session_id` still returns 200. Requires `X-API-Key`.

```json
{ "deleted": true, "session_id": "3f9c2e7a1b4d4f6e8a0c2d5e7f9a1b3c" }
```

## Health endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/v1/health/` | open | Liveness + version. Used by the Docker healthcheck |
| `GET /api/v1/health/live` | open | Minimal liveness probe |
| `GET /api/v1/health/ready` | open | Readiness probe with per-dependency checks |
| `GET /api/v1/health/notion-health` | open | Verifies Notion credentials via `users.me` |
| `GET /api/v1/health/status` | `X-API-Key` | Version, environment, uptime, host system info |

`GET /api/v1/health/` returns:

```json
{
  "status": "healthy",
  "timestamp": "2026-08-16T10:30:00Z",
  "version": "0.1.0",
  "service": "WebToNotion"
}
```

`notion-health` returns 401 if the Notion token is rejected and 503 if the Notion API is
unreachable, which makes it the fastest way to confirm credentials after a deploy.

## Rate limits outside your control

Beyond this service's own per-IP limit, requests are bounded by:

- **Notion** — the client is throttled to 3 requests/second internally
- **Groq** — transcription is subject to your account's quota
- **OpenRouter** — two agent calls per request (analysis + mapping)
- **Video platforms** — some throttle or block datacenter IPs; see
  [`COOKIES_FILE_PATH`](configuration.md#video-extraction)
