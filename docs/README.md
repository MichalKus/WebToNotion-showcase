# WebToNotion Documentation

WebToNotion is a FastAPI service that takes a video URL, extracts and transcribes it,
analyses the content with AI, and creates a structured page in a Notion database.

| Document | Read it for |
|---|---|
| [architecture.md](architecture.md) | How the pieces fit together, request flow, layering rules |
| [api.md](api.md) | Endpoints, request/response shapes, error codes |
| [configuration.md](configuration.md) | Every environment variable, defaults, and known traps |
| [video-processing.md](video-processing.md) | The extraction → transcription → analysis pipeline |
| [notion-integration.md](notion-integration.md) | Schema-driven mapping to user-defined databases |
| [deployment.md](deployment.md) | CI/CD, environments, release process |

Setup and installation are in the [root README](../README.md).

## Quick orientation

```
POST /api/v1/process/url  →  yt-dlp  →  Groq Whisper  →  OpenRouter  →  Notion page
```

Four credentials are required: `NOTION_API_KEY`, `OPENROUTER_API_KEY`, `WHISPER_API_KEY`
(Groq), and `API_KEY` (this service's own). See
[configuration.md](configuration.md#required).

## Conventions

These docs describe what the code does today. Where behaviour is surprising or a setting
is a trap, it is called out inline rather than smoothed over. If you find a claim here that
the code contradicts, the code is right and the doc is a bug.
