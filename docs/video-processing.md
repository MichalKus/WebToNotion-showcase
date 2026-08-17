# Video Processing

How `VideoScrapingService.process_video` turns a URL into a `VideoContent`.

```
URL → cache lookup → yt-dlp extract → Groq transcribe → OpenRouter analyse → cache write
```

Every step after the cache lookup is skipped on a cache hit.

## Supported platforms

`is_video_url` does a case-insensitive substring match against these patterns:

```
youtube.com      youtu.be         vimeo.com        dailymotion.com
twitch.tv        tiktok.com       twitter.com      x.com
facebook.com/watch                facebook.com/share
instagram.com/reel
```

Facebook and Instagram match only on those specific path prefixes — a bare
`instagram.com/p/...` post URL is rejected with HTTP 400.

To add a platform, extend `VIDEO_PLATFORM_PATTERNS` in `services/video_scraping_service.py`.
yt-dlp itself supports far more sites than this list; the list is the deliberate allowlist.

## Prerequisites

- **Python 3.12+**
- **ffmpeg on `PATH`** — yt-dlp uses it to extract audio, and `pydub` uses it to normalise
  non-mp3 downloads

  ```bash
  choco install ffmpeg          # Windows
  brew install ffmpeg           # macOS
  sudo apt install ffmpeg       # Debian/Ubuntu
  ```

- **`WHISPER_API_KEY`** — a Groq API key
- **`OPENROUTER_API_KEY`** — used by both AI agents

`ContentAnalyzer` and the Notion mapper agent raise `ValueError` at import time if
`OPENROUTER_API_KEY` is missing, so the app will not start without it.

## Extraction (yt-dlp)

`YtDlpExtractor.extract` runs `extract_info(download=False)` first to get metadata, then
downloads audio in a second pass.

Metadata captured into `ExtractionData`: title, description, uploader, duration, upload
date, plus `platform`, `view_count`, `like_count`, and `video_id` in `metadata`.

Notable yt-dlp options (`ytdlp_extractor.py`):

| Option | Source | Effect |
|---|---|---|
| `format` | fixed | `bestaudio/best` |
| `max_filesize` | `MAX_FILE_SIZE` | Aborts oversized downloads |
| `socket_timeout` | `REQUEST_TIMEOUT` | Per-connection timeout |
| `retries` / `fragment_retries` | `MAX_RETRIES` | Transient failure retries |
| `audioquality` | `AUDIO_QUALITY` | `best`→0 (VBR), `good`→192k, `medium`→128k |
| `cookiefile` | `COOKIES_FILE_PATH` | Only set if the file exists; logs a warning if configured but absent |
| `geo_bypass` | fixed | Enabled |

### Duration limit

If `duration > MAX_VIDEO_DURATION`, the audio download is **skipped entirely**. Extraction
still succeeds — you get metadata, no transcript, and `skipped_transcription:
"duration_exceeded"` in `VideoContent.metadata`. Analysis then runs on title and
description alone.

### Audio normalisation

Audio lands in `TEMP_DIR/{video_id}.mp3`. If yt-dlp produced webm, m4a, or wav instead,
`pydub` converts it to mono 16 kHz mp3 and deletes the original. An existing file at that
path is reused without re-downloading.

## Transcription (Groq Whisper)

`AudioTranscriber.transcribe` posts the file to Groq's
`audio.transcriptions.create` with `response_format="text"`, using `WHISPER_MODEL`
(default `whisper-large-v3`).

When `CLEANUP_TEMP_FILES=true`, the audio file is deleted afterwards — on both success and
failure — but only if it sits directly in `TEMP_DIR`.

A transcription failure is logged and swallowed: processing continues with an empty
transcript rather than aborting the request.

## Analysis (OpenRouter + PydanticAI)

`ContentAnalyzer` runs a PydanticAI `Agent` with `output_type=ContentAnalysisResult`, so
the model must return a structurally valid object or PydanticAI retries (`MAX_RETRIES`).

```python
class ContentAnalysisResult(BaseModel):
    topics: list[str]          # 1–10 entries
    sentiment: str             # "positive" | "negative" | "neutral"
    locations: list[str]       # up to 20
    key_insights: list[str]    # up to 10
    content_category: str      # default "general"
```

The prompt is truncated before sending: description to 1000 characters, transcript to
2000. Long videos are therefore analysed on their opening minutes, not their full text.

On any failure the analyser returns an empty result with `sentiment="neutral"` instead of
raising. Quota, rate-limit, and authentication errors are detected and logged with a
specific hint, but the request still completes.

`key_insights` and `content_category` are folded into `VideoContent.metadata`, with
`key_insights` stored as a JSON-encoded string.

## Caching

`FileCacheService` writes `VideoContent` as JSON to `CACHE_DIR/{md5(url)}.json`.

- Enabled by `ENABLE_CACHING` (default true)
- `CACHE_EXPIRATION` in seconds; `0` means never expire
- Expiry is checked against the file's mtime at read time — stale files are ignored but not
  deleted, so the cache directory grows until cleaned manually
- Cache read and write failures are logged as warnings and never fail the request

To clear the cache, delete the contents of `CACHE_DIR`.

## Failure behaviour

| Step | On failure |
|---|---|
| Cache read | Warn, treat as miss |
| yt-dlp extraction | **Aborts** — wrapped in `VideoScrapingError` → HTTP 422 |
| Transcription | Warn, continue with empty transcript |
| Analysis | Return neutral/empty result, continue |
| Cache write | Warn, continue |

Extraction is the only hard failure. Everything downstream degrades.

There is **no Playwright fallback**. `PlaywrightFallbackError` and `PlaywrightError` exist
in `exceptions.py` and some docstrings still mention a fallback, but no such code path is
implemented and Playwright is not a dependency.

## Testing

```bash
pytest tests/unit/                                  # mocked, no network
pytest tests/integration/                           # hits live endpoints
pytest tests/ -m "not slow and not requires_api_keys"
```

`tests/conftest.py` auto-applies the `integration`, `slow`, `requires_api_keys`, and
`requires_internet` markers based on test path and name.

## Troubleshooting

**`ffmpeg not found`** — install it and confirm it's on `PATH`. Without it, audio
extraction fails and every video processes without a transcript.

**Video is private or unavailable** — set `COOKIES_FILE_PATH` to a Netscape-format
cookies file. Instagram, Facebook, and TikTok frequently require this from datacenter IPs.

**No transcript on a long video** — check for `skipped_transcription` in the response
metadata, then raise `MAX_VIDEO_DURATION`.

**Analysis returns empty topics** — the analyser degraded silently. Check the logs for an
OpenRouter quota or authentication error.

**`OpenRouter API key is required`** at startup — set `OPENROUTER_API_KEY`; both agents
construct at import time.
