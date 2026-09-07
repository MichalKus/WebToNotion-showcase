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

`AudioTranscriber.transcribe` posts the file to Groq's `audio.transcriptions.create`
with `response_format="verbose_json"`, using `WHISPER_MODEL` (default
`whisper-large-v3`). `verbose_json` costs the same as `text` and additionally
returns per-segment start/end timestamps, which is what lets `ask_about_video`
cite a position in the video rather than just quoting text. The result is a
`StoredTranscript`: full `text`, detected `language`, `duration`, and a list of
`TranscriptSegment` (`start`, `end`, `text`). A model or response that carries no
segment data still transcribes fine — `segments` is simply empty; text is the
load-bearing part, timestamps are an enhancement.

When `CLEANUP_TEMP_FILES=true`, the audio file is deleted afterwards — on both success and
failure — but only if it sits directly in `TEMP_DIR`.

What happens to a transcription failure depends on the caller:

- `VideoScrapingService.fetch_transcript` (used by the chat orchestrator's video
  tools) lets it propagate as `VideoScrapingError` — there is no page to build a
  degraded version of in a chat turn, so the tool reports the failure and the
  agent explains it to the user.
- `VideoScrapingService.process_video` (the fixed `/process/url` pipeline) still
  logs and swallows it, continuing with an empty transcript, exactly as before
  this PR.

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

On any failure the analyser raises `ContentProcessingError` — it no longer returns an
empty, `sentiment="neutral"` result. A silent empty result is indistinguishable from a
genuine "this video has no discernible topics" answer, and an agent (or a person) reading
it downstream would believe it; a typed failure is not mistakeable for a real analysis.
Quota, rate-limit, and authentication errors are still detected and logged with a specific
hint before the exception is raised.

`key_insights` and `content_category` are folded into `VideoContent.metadata`, with
`key_insights` stored as a JSON-encoded string.

## The three pipeline stages

`VideoScrapingService` exposes three independently callable, independently cached
stages, rather than one monolithic `process_video`:

| Stage | Method | Downloads audio? | Cached artifact |
|---|---|---|---|
| Metadata | `fetch_metadata` | no | `metadata` |
| Transcript | `fetch_transcript` | yes | `metadata` (under the `transcript` key) |
| Analysis | `analyze_content` | no (reuses the transcript) | `analysis` |

The chat orchestrator's video tools call these directly and one at a time —
answering "what is this video?" must not trigger an audio download and a Whisper
call it doesn't need. `process_video` still exists and still composes all three
into one `VideoContent` for the fixed `/process/url` endpoint, unchanged.

Caching each stage the moment it succeeds, rather than only the final assembled
blob, is what makes a failure cheap: before this decomposition, an analysis
failure discarded an already-completed Whisper transcription along with it,
because nothing was written to disk until the whole pipeline finished. Now
`fetch_transcript` persists the transcript into the `metadata` artifact before
analysis ever runs, so a flaky OpenRouter call costs a re-run of `analyze_content`
alone, never a second transcription.

## Caching

`FileCacheService` keys cache entries `(url_hash, artifact)` rather than one
whole-`VideoContent` blob, written to
`CACHE_DIR/{md5(url)}.{artifact}.json`. `artifact` is one of `metadata`, `analysis`,
or `content` (the legacy whole-blob entry `process_video` still writes and reads for
the fixed pipeline).

The `metadata` artifact is the single file that holds everything durable about a
video — its title/author, its generated `summaries` keyed by `(style, length)`, and
its full `transcript` (text plus timestamped segments) once transcribed.

- Enabled by `ENABLE_CACHING` (default true)
- **Per-artifact TTL.** `analysis` and `content` expire on `CACHE_EXPIRATION`
  (default 1 day) because a prompt or model change should invalidate them. The
  `metadata` artifact expires on `TRANSCRIPT_TTL` (default 30 days) instead: none of
  what it holds goes stale, and re-running Whisper is the most expensive operation in
  the system. `0` means never expire, for either.
- Expiry is checked against the file's mtime at read time — stale files are ignored but not
  deleted, so the cache directory grows until cleaned manually
- Cache read and write failures are logged as warnings and never fail the request
- **Writes are atomic** — serialized to a sibling temp file, fsynced, then
  `os.replace`d over the target — so a crash or a concurrent read never sees a
  half-written file and the expensive `metadata` artifact cannot be lost to a torn
  write
- **Concurrent writers are serialized per file.** Every read-modify-write of the
  shared `metadata` artifact (persisting a transcript, storing a summary,
  seeding metadata) runs under a process-wide `asyncio.Lock` keyed on
  `(url, artifact)`, re-reading and merging under the lock rather than
  overwriting. `fetch_transcript` holds that lock across extraction and Whisper,
  so two chat turns about the same new video transcribe it once, not twice. This
  is in-process only — with `WORKERS > 1` the atomic write still rules out
  corruption, but a lost update degrades to last-write-wins

To clear the cache, delete the contents of `CACHE_DIR`.

## The transcript in chat context

Only `TranscriptRef` — a hash, character count, segment count, duration,
language, and a short preview — ever reaches chat context or conversation
history. `TranscriptRef.from_transcript` mints it; the transcript body is read back
from the `metadata` artifact on demand, only inside the ephemeral sub-agent runs
described under [Prompt caching](#prompt-caching) below.

## Video tools

Four tools, in `agents/tools/video.py`, are the chat orchestrator's read path
over a video. Every one returns a small Pydantic model sized for chat context —
never the transcript itself — and every one turns a recoverable failure into a
structured `ToolError` rather than an exception, so the agent can see the failure,
explain it, and offer alternatives instead of the run aborting into a 500.
Recoverable covers a geo-blocked video, a missing audio track, **and** a transient
model-provider failure inside a `summarize` / `ask_about_video` sub-agent run
(a provider 5xx or 429, a dropped connection, an unparseable response). A
misconfiguration — a missing or rejected API key (HTTP 401/403) — still raises,
and a per-turn usage-budget overrun still propagates as HTTP 429 (see
[api.md](api.md)).

| Tool | Calls | Returns |
|---|---|---|
| `get_video_metadata` | `fetch_metadata` | `VideoMetadata` — title, author, duration, platform, published date. Never downloads audio. |
| `get_transcript` | `fetch_transcript` | `TranscriptRef` — a handle to the transcript, not the transcript |
| `summarize` | `fetch_transcript`, then a summarization sub-agent | `SummaryResult` — the summary text, cached in video metadata per `(style, length)` pair |
| `ask_about_video` | `fetch_transcript`, then an answering sub-agent | `AnswerResult` — an answer plus the timestamped excerpts it rests on |

`summarize` and `ask_about_video` cache and reuse their sub-agent outputs the
same way the pipeline stages do: a summary is written directly to the video's
`metadata` artifact under its `summaries` dictionary (keyed by `<style>:<length>`)
the first time it's produced, so asking for the same style and length again is a
cache hit, not a second model call.

## Prompt caching

Every sub-agent prompt goes through the single builder,
`agents/prompts.build_transcript_prompt`, which assembles a fixed-format
prefix — a framing header plus the transcript, segment index, or summary,
wrapped in `<video_material>` tags — followed by a `CachePoint`, followed by the
question. Because the prefix is a pure function of the material and never of
anything run-dependent (no timestamp, no turn counter, no re-ordered header), a
provider prompt cache can reuse it across calls: five follow-up questions about
one video cost roughly 1.65x one question, not 5x.

**That saving depends entirely on nothing variable appearing ahead of the
transcript.** A single timestamp or per-run header inserted before the
`CachePoint` breaks the cache silently — every call still succeeds, it just
costs full price every time, with nothing in the response to flag it.
`tests/unit/test_transcript_prompt.py` asserts the prefix never drifts; any new
caller must go through `build_transcript_prompt` rather than assembling its own
prompt. `CachePoint` is filtered out by providers that don't support caching, so
it is safe to leave in place on any model. Its TTL is `PROMPT_CACHE_TTL`
(`"5m"` or `"1h"`, default `"1h"`).

## Escalation and map-reduce

Two mechanisms bound sub-agent cost beyond prompt caching:

**Escalation** (`agents/subagents.answer_question`) — a question first runs
against a compact context: a cached summary plus a timestamped segment index
sampled evenly across the video (roughly 1-2k tokens, versus ~13.5k for a full
hour-long transcript). The sub-agent's structured output reports whether that
context was `sufficient`; only when it is not does a second pass run against the
full transcript. Most follow-up questions never need the raw text.

**Map-reduce above a ceiling** (`agents/subagents.summarize_text`) — a
transcript longer than `SUMMARY_MAP_REDUCE_THRESHOLD_CHARS` (default 120,000
characters) is summarized in windows of `SUMMARY_MAP_REDUCE_WINDOW_CHARS`
(default 20,000 characters each), then the per-window summaries are reduced into
one final summary. This bounds the cost of summarizing regardless of the model's
context limit, so one pathological six-hour stream cannot produce a surprise
bill.

## Failure behaviour

For the fixed `process_video` pipeline behind `/process/url`:

| Step | On failure |
|---|---|
| Cache read | Warn, treat as miss |
| yt-dlp extraction | **Aborts** — wrapped in `VideoScrapingError` → HTTP 422 |
| Transcription | Warn, continue with empty transcript |
| Analysis | **Aborts** — `ContentProcessingError`, wrapped in `VideoScrapingError` → HTTP 422 |
| Cache write | Warn, continue |

Extraction and analysis are hard failures; transcription is the only step that
still degrades gracefully in this pipeline.

The chat orchestrator's video tools behave differently: `fetch_transcript` also
aborts on a transcription failure (there is no page to degrade into a thinner
version of mid-conversation), but the tool layer catches it — along with
`ContentProcessingError` — and turns it into a `ToolError` the agent can see and
explain, rather than letting it surface as a 500. See
[Video tools](#video-tools) above.

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

**`/process/url` returns 422 with "Content analysis failed"** — `ContentAnalyzer`
raised `ContentProcessingError`. Check the logs for an OpenRouter quota, rate-limit,
or authentication error; the analyser no longer degrades to an empty result.

**A follow-up question about a video re-transcribes it** — check `TRANSCRIPT_TTL`;
the `metadata` artifact that carries the transcript may have expired, or the tool
may be receiving a different URL (the cache keys on an exact MD5 of the URL string,
so a trailing tracking parameter counts as a different video).

**`OpenRouter API key is required`** at startup — set `OPENROUTER_API_KEY`; both agents
construct at import time.
