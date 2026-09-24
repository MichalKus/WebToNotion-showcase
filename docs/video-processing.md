# Video Processing

How `VideoScrapingService` turns a URL into the material a Notion page is built from.

```
URL → cache lookup → yt-dlp extract (metadata) → Groq transcribe (audio) → cache write
```

There is no separate analysis stage. `VideoScrapingService` exposes independently callable,
independently cached steps — `is_video_url`, `fetch_metadata`, `fetch_transcript`,
`store_summary` — and both `agents/writer.py` (behind `POST /api/v1/process/url`) and the
chat orchestrator's video tools call those steps directly. Summaries are produced **on
demand** by a chat sub-agent and cached, never by this service. Every step after the cache
lookup is skipped on a cache hit.

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
- **`OPENROUTER_API_KEY`** — used by the Notion mapper agent and the chat orchestrator /
  sub-agents

Agents are built lazily by `build_*(settings)` factories, not at module import, so a missing
`OPENROUTER_API_KEY` no longer breaks startup or test collection — it fails the first agent
run instead.

## Extraction (yt-dlp)

`YtDlpExtractor` has two passes: `extract_metadata` runs `extract_info(download=False)`,
and `fetch_audio` downloads the audio track. The second pass reuses the first pass's result
instead of extracting again (see [Resolved-info cache](#resolved-info-cache)).

Metadata captured into `ExtractionData`: title, description, uploader, duration, upload
date, plus `platform`, `view_count`, `like_count`, and `video_id` in `metadata`.

On a typical 4-minute YouTube video, metadata takes ~1.7 s and the audio pass ~2.5 s
(download plus mp3 transcode).

### Fast and full profiles

Extraction tries a **fast** profile first and falls back to a **full** one if the fast one
raises:

| Profile | YouTube clients | Watch page | Cookies | Why |
|---|---|---|---|---|
| fast | `android` | skipped (`player_skip: webpage`) | never | ~1.5 s; `android` needs no JS player |
| full | `android`, `web` | fetched | `COOKIES_FILE_PATH` if set | Age gates, login-gated content on any platform, clearer errors |

**Why `android`.** Without a PO Token (YouTube's anti-bot attestation — see the
[yt-dlp PO Token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)), `android`
is the only client that serves a downloadable format: itag 18, a 360p muxed mp4 with
`ratebypass=yes`, so it downloads at full speed. As of yt-dlp 2026.08:

- `android` and `android_vr` still *list* audio-only formats (139/140/249/251), but
  downloading them returns HTTP 403.
- `mweb` needs a GVS PO Token and is skipped.
- `web` is SABR-only: it returns no plain stream URLs.

So audio comes from itag 18 (~10 MB for 4 minutes, ~165 MB for an hour, most of it video)
and is transcoded to mp3. Getting audio-only downloads would need a PO Token provider
plugin (e.g. `bgutil-ytdlp-pot-provider`). That isn't set up — revisit it if itag 18 starts
returning 403 or disappears.

**Why the fast profile never sends cookies.** Once a cookies file authenticates the
session, yt-dlp drops every client that doesn't support cookies — `android` included — and
only SABR-only `web` is left, so nothing can be downloaded. Cookies are therefore used only
in the full profile. In practice they help with other platforms and with metadata for
gated YouTube videos, **not** with downloading YouTube audio.

### Options

Notable yt-dlp options (`YtDlpExtractor._build_opts`):

| Option | Source | Effect |
|---|---|---|
| `format` | fixed | `bestaudio/best[height<=480]/best` — audio-only where offered, else a small muxed file rather than HD video |
| `noplaylist` | fixed | A watch URL with `&list=…` (from a playlist or mix) resolves to the single video |
| `extract_flat` | fixed | `in_playlist` — a bare playlist URL is rejected without resolving every entry |
| `ignoreerrors` / `ignore_no_formats_error` | fixed | Both `False`, so errors raise with their real cause (see below) |
| `logger` | fixed | yt-dlp output goes to the app logger, not stdout; `quiet` and `noprogress` are on |
| `verbose` | `VERBOSE_LOGGING` | Adds yt-dlp's `[debug]` lines (logged at DEBUG) |
| `max_filesize` | `MAX_FILE_SIZE` | Aborts oversized downloads |
| `socket_timeout` | `REQUEST_TIMEOUT` | Per-connection timeout, capped at 30 s |
| `retries` / `fragment_retries` | `MAX_RETRIES` | Transient failure retries |
| `source_address` | fixed | `0.0.0.0` — forces IPv4 (kept from the original throttling fix, not measured on its own) |
| `js_runtimes` | fixed | `node`, `deno` — only the full profile's `web` client needs one; the Docker image ships deno. The challenge-solver scripts come from the `yt-dlp-ejs` package, never fetched from GitHub at runtime |
| `postprocessor_args` | `AUDIO_QUALITY` | Mono 16 kHz mp3: `best`→48k, `good`→32k, `medium`→24k (anything else 32k) |
| `cookiefile` | `COOKIES_FILE_PATH` | Full profile only. Set only if the file exists; logs a warning if configured but absent |

**Unavailable videos fail loudly.** With `ignore_no_formats_error=True`, a deleted,
private, or mistyped video used to "succeed" with a made-up title (`youtube video #<id>`)
and no formats, and that would have gone into Notion as a page. Now it raises
`This video is unavailable` → `VideoScrapingError` → HTTP 422. The downside: a video that
has metadata but nothing downloadable (e.g. an upcoming premiere) also fails with 422,
instead of producing a page built from its title alone.

**Playlist URLs.** `youtube.com/watch?v=X&list=Y` processes video `X`. A bare
`youtube.com/playlist?list=Y` raises `URL points to a playlist, not a single video` (422).

### Resolved-info cache

`extract_metadata` keeps yt-dlp's resolved info dict in a process-local, in-memory cache
(module level in `ytdlp_extractor.py`, because extractor instances are created per
request). The audio pass pops it and downloads with `process_ie_result(info, download=True)`,
skipping a second extraction:

- **TTL 30 minutes**, at most **16 entries** (LRU). Signed stream URLs expire after ~6 h.
- **Trimmed before storing** — `automatic_captions`, `subtitles`, `thumbnails`, and
  `heatmap` are dropped. `automatic_captions` alone is ~11 MB per video; `formats` is ~15 KB.
- **One-shot** — the entry is removed when used, since yt-dlp mutates it during download.
- **Fallback** — on a miss, an expired entry, or a failed download from it (e.g. a 403),
  the audio pass extracts again (fast → full profile) and downloads from that result.

The cache is never written to disk. Stream URLs go stale within hours and embed the
server's IP. With several uvicorn workers, a hit needs both passes to land in the same
process. That is always true within one `/process/url` request, not necessarily across
chat turns.

### Expected yt-dlp warnings

Every YouTube request logs this at WARNING level:

```
[youtube] <id>: Some android client https formats have been skipped as they are missing
a URL. YouTube may have enabled the SABR-only streaming experiment for the current
session. See https://github.com/yt-dlp/yt-dlp/issues/12482 for more details
```

**This is normal and expected — do not treat it as an error or try to fix it.** YouTube
serves most `android` formats only over SABR, its own streaming protocol, which yt-dlp
skips. What's left includes itag 18, the format this service downloads. As long as the
next log lines show metadata and `Download completed`, nothing is wrong. It only matters
if it comes with `Requested format is not available` or `No video formats found` — that
means itag 18 is gone too (see [Troubleshooting](#troubleshooting)).

Other messages that can show up without anything being wrong:

- `Fast yt-dlp extraction failed, retrying with full profile: …` — the fallback working
  as designed. Only the full profile's failure fails the request.
- `Download from resolved formats failed, re-extracting: …` — a stale cached stream URL.
  The audio pass extracts again.
- yt-dlp's own `ERROR:` lines are logged at WARNING, because the caller logs the raised
  exception with context, and a fast-profile failure the fallback recovers from shouldn't
  read as an error.

### Duration limit

If `duration > MAX_VIDEO_DURATION`, the audio download is **skipped entirely**. Extraction
still succeeds — you get metadata and no transcript. The Notion mapper then works from the
title and description alone.

### Audio normalisation

Audio lands in `TEMP_DIR/{video_id}.mp3`, already mono 16 kHz at the `AUDIO_QUALITY`
bitrate: yt-dlp's `FFmpegExtractAudio` does the transcode. If a non-mp3 file ends up there
instead (webm, m4a, wav), `pydub` converts it with the same settings and deletes the
original. An existing file at that path is reused without re-downloading.

Whisper resamples to 16 kHz mono anyway, so a higher bitrate only makes the upload bigger.
At `best` (48k), a one-hour video is ~22 MB, under Groq's 25 MB file limit. The old
192 kbps stereo output went over that limit after ~17 minutes.

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

`VideoScrapingService.fetch_transcript` always lets a transcription failure propagate as
`VideoScrapingError`. What happens next depends on the caller:

- The chat orchestrator's video tools (`get_transcript`, `summarize`, `ask_about_video`)
  turn it into a `ToolError` — there is no page to build a degraded version of in a chat
  turn, so the agent explains the failure to the user.
- `agents/writer.build_page_content` (behind `POST /api/v1/process/url`) calls
  `fetch_transcript` tolerantly: a no-audio / transcription `VideoScrapingError` is logged
  and yields an empty `transcript_excerpt`, and the page is still built from metadata. A
  `fetch_metadata` failure, by contrast, propagates and fails the request with 422.

## No analysis stage

There is no `ContentAnalyzer`. The `topics` / `sentiment` / `locations` / `key_insights`
extraction pass was removed in the single-write-path refactor and **not** backfilled. The
Notion mapper agent (`services/analysis/notion_mapper.py`) now infers a database's
properties directly from the title, description, transcript excerpt, and any cached summary
that `agents/writer.build_page_content` assembles into a `VideoPageContent` — see
[notion-integration.md](notion-integration.md).

## The pipeline stages

`VideoScrapingService` exposes independently callable, independently cached steps rather
than one monolithic `process_video`:

| Step | Method | Downloads audio? | Cached artifact |
|---|---|---|---|
| Video-URL check | `is_video_url` | no | — |
| Metadata | `fetch_metadata` | no | `metadata` |
| Transcript | `fetch_transcript` | yes | `metadata` (under the `transcript` key) |
| Summary store | `store_summary` | no | `metadata` (under `summaries`) |

Both the chat orchestrator's video tools and `agents/writer.build_page_content` call these
directly and one at a time — answering "what is this video?" must not trigger an audio
download and a Whisper call it doesn't need. There is no `process_video` and no
`analyze_content`.

Caching each step the moment it succeeds, rather than only a final assembled blob, is what
makes a failure cheap: `fetch_transcript` persists the transcript into the `metadata`
artifact before anything downstream runs, so a flaky mapper call never costs a second
transcription.

## Caching

`FileCacheService` keys cache entries `(url_hash, artifact)` rather than one
whole-`VideoContent` blob, written to
`CACHE_DIR/{md5(url)}.{artifact}.json`. With the pipelines collapsed into one write path,
`metadata` is the only artifact still written — the legacy whole-blob `content` entry went
away with `process_video`, and nothing produces an `analysis` artifact now that
`analyze_content` / `ContentAnalyzer` are gone.

The `metadata` artifact is the single file that holds everything durable about a
video — its title/author, its generated `summaries` keyed by `(style, length)`, and
its full `transcript` (text plus timestamped segments) once transcribed.

- Enabled by `ENABLE_CACHING` (default true)
- The `metadata` artifact expires on `TRANSCRIPT_TTL` (default 30 days): none of what it
  holds goes stale, and re-running Whisper is the most expensive operation in the system.
  `0` means never expire.
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

For `POST /api/v1/process/url` (via `agents/writer.py`):

| Step | On failure |
|---|---|
| Cache read | Warn, treat as miss |
| yt-dlp metadata (`fetch_metadata`) | **Aborts** — `VideoScrapingError` → HTTP 422, including unavailable videos, videos with no downloadable formats, and playlist URLs |
| Transcription (`fetch_transcript`) | Logged and swallowed — the page is built with an empty transcript excerpt |
| Notion mapper agent | **Aborts** — `ContentProcessingError` → HTTP 500 |
| Notion `create_page` | **Aborts** — `NotionAuthenticationError` → 401, `NotionAPIError` → 503 |
| Cache write | Warn, continue |

Metadata extraction and the mapper are hard failures; transcription is the only step that
degrades gracefully.

The chat orchestrator's video tools behave differently: `fetch_transcript` still aborts on a
transcription failure (there is no page to degrade mid-conversation), but the tool layer
catches it — along with `ContentProcessingError` — and turns it into a `ToolError` the agent
can explain, rather than letting it surface as a 500. See [Video tools](#video-tools) above.

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
On YouTube, cookies only reach the full profile and don't help with audio downloads (see
[Fast and full profiles](#fast-and-full-profiles)). A genuinely deleted, private, or
mistyped video fails with HTTP 422 and `This video is unavailable`.

**"Some android client https formats have been skipped … SABR-only streaming"** in the
logs — expected on every YouTube request; ignore it. See
[Expected yt-dlp warnings](#expected-yt-dlp-warnings).

**YouTube audio stopped downloading (`Requested format is not available`, `No video formats
found`, or HTTP 403 on every video)** — itag 18 from the `android` client has probably been
withdrawn or locked behind a PO Token. Update yt-dlp first (`pip install -U yt-dlp
yt-dlp-ejs`). If that doesn't help, set up a PO Token provider plugin and add a
token-capable client (e.g. `mweb`) to the fast profile in `_build_opts`.

**`URL points to a playlist, not a single video`** — the URL is a bare playlist
(`/playlist?list=…`). Send a single video's watch URL instead. Watch URLs with `&list=` work.

**No transcript on a long video** — a video longer than `MAX_VIDEO_DURATION` skips the audio
download entirely (`transcript_length: 0`, `transcription_available: false` in the
response). Raise `MAX_VIDEO_DURATION` if you need the transcript.

**`/process/url` returns 500 with "Notion mapping failed"** — the Notion mapper agent
raised `ContentProcessingError` (a model error or retry exhaustion). Check the logs for an
OpenRouter quota, rate-limit, or authentication error. This was a misleading 503 before the
write moved onto the shared path.

**A follow-up question about a video re-transcribes it** — check `TRANSCRIPT_TTL`;
the `metadata` artifact that carries the transcript may have expired, or the tool
may be receiving a different URL (the cache keys on an exact MD5 of the URL string,
so a trailing tracking parameter counts as a different video).

**`OpenRouter API key is required`** on the first agent run — set `OPENROUTER_API_KEY`.
Agents are built lazily now, so a missing key surfaces at run time rather than at import.
