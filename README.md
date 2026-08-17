# WebToNotion

A FastAPI service that turns a video URL into a structured Notion page.

Give it a link to a YouTube, Vimeo, TikTok, Instagram, Facebook, Twitch, or X video and a
Notion database ID. It extracts the video with yt-dlp, transcribes the audio with Groq
Whisper, analyses the content with an AI agent, then maps the result onto whatever schema
your database happens to have and creates the page.

```
POST /api/v1/process/url  →  yt-dlp  →  Groq Whisper  →  OpenRouter  →  Notion page
```

## What it does

- **Works with any database schema.** Property names and types vary between workspaces, so
  the schema is fetched from Notion and injected into a PydanticAI agent, whose output is
  validated against that schema and retried on mismatch. No per-database configuration.
- **Extracts, transcribes, analyses.** Metadata and audio via yt-dlp, transcription via
  Groq Whisper, then topics, sentiment, locations, and key insights via OpenRouter.
- **Degrades instead of failing.** A transcription or analysis failure still produces a
  page — a thinner one. Only extraction is a hard failure.
- **Caches processed videos** to avoid paying for the same URL twice.
- **Observability** through Logfire, with structured logging throughout.

## Requirements

- Python 3.12+
- **ffmpeg on `PATH`** — used for audio extraction
- A Notion integration token, shared with each target database
- An OpenRouter API key and a Groq API key

## Install

```bash
git clone https://github.com/MichalKus/WebToNotion.git && cd WebToNotion
```

```bash
python -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
```

```bash
pip install -e ".[dev]"
```

## Configure

```bash
cp .env.example .env
```

Four values are required:

```env
NOTION_API_KEY=your_notion_integration_token
OPENROUTER_API_KEY=your_openrouter_key
WHISPER_API_KEY=your_groq_key
API_KEY=a_key_clients_will_send_as_X-API-Key
```

Create the Notion integration at [notion.so/my-integrations](https://www.notion.so/my-integrations),
then share each target database with it — the integration cannot see a database until you do.

Every other setting, along with the traps worth knowing about, is documented in
[docs/configuration.md](docs/configuration.md).

## Run

```bash
python -m webtonotion.main
```

```bash
uvicorn webtonotion.main:create_app --host 0.0.0.0 --port 8000
```

Interactive API docs are at `/docs`.

### Process a video

```bash
curl -X POST "http://localhost:8000/api/v1/process/url" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","database_id":"YOUR_DB_ID"}'
```

### Docker

```bash
docker build -t webtonotion -f docker/Dockerfile .
```

```bash
docker run -d -p 8000:8000 --env-file .env --name webtonotion webtonotion
```

## Documentation

| Document | Covers |
|---|---|
| [architecture.md](docs/architecture.md) | How the pieces fit together, request flow, layering |
| [api.md](docs/api.md) | Endpoints, payloads, error codes |
| [configuration.md](docs/configuration.md) | Every setting and its defaults |
| [video-processing.md](docs/video-processing.md) | The extraction and analysis pipeline |
| [notion-integration.md](docs/notion-integration.md) | Schema-driven page mapping |
| [deployment.md](docs/deployment.md) | CI/CD, environments, releases |

## Development

```bash
pytest tests/unit/
```

```bash
black src/ tests/ && isort src/ tests/ && flake8 src/ tests/ && mypy src/
```

`tests/unit/` is mocked and runs offline. `tests/integration/` hits live external
endpoints and needs API keys. Only unit tests run in CI.

`flake8` and `mypy` are not wired into CI — run them locally before opening a PR.

## Contributing

Branch names follow `feature/amazing-feature`, and feature branches PR directly into
`master`. There is no `develop` branch.

Two things will block a PR: the title must parse as a Conventional Commit
(`feat:`, `fix:`, `docs:`, `chore:`), and `version` in `pyproject.toml` must be a semver
increase over `master` — every merge to `master` is a release.

**Opening a PR deploys to the shared dev VPS.** Pushing a feature branch on its own does
not. To preview a branch before opening a PR, dispatch the deploy manually:

```bash
gh workflow run deploy.yml --ref feature/your-branch-name
```

See [docs/deployment.md](docs/deployment.md).

## License

MIT — see [LICENSE](LICENSE).

## Built with

[FastAPI](https://fastapi.tiangolo.com/) ·
[PydanticAI](https://ai.pydantic.dev/) ·
[yt-dlp](https://github.com/yt-dlp/yt-dlp) ·
[Groq](https://groq.com/) ·
[OpenRouter](https://openrouter.ai/) ·
[Notion API](https://developers.notion.com/) ·
[Logfire](https://logfire.pydantic.dev/)
