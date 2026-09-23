"""Video scraping service for extracting content from video URLs.

The service exposes three independently callable, independently cached stages --
metadata, transcript, and summary-store -- because the agentic flow needs them one at
a time (answering "what is this video?" must not download audio) and because each
must be cached the moment it succeeds.

The transcript is persisted *inside* the ``metadata`` cache artifact -- one file per
video holds its title/author, its cached summaries, and its transcript -- because none
of that goes stale and re-running Whisper is the most expensive operation here. The
``metadata`` artifact therefore keeps the long ``transcript_ttl`` (see
``services/storage/file_cache.py``).
"""

from typing import Any, Optional

from pydantic import HttpUrl

from webtonotion.config.logging import LoggerMixin
from webtonotion.exceptions import VideoScrapingError
from webtonotion.models.transcript import StoredTranscript
from webtonotion.services.analysis.transcriber import AudioTranscriber
from webtonotion.services.extraction.base import ExtractionData
from webtonotion.services.extraction.ytdlp_extractor import YtDlpExtractor
from webtonotion.services.storage.file_cache import FileCacheService


class VideoScrapingService(LoggerMixin):
    """Extracts and transcribes video content, one cached stage at a time."""

    # Supported video platforms
    VIDEO_PLATFORM_PATTERNS = [
        "youtube.com",
        "youtu.be",
        "vimeo.com",
        "dailymotion.com",
        "twitch.tv",
        "facebook.com/watch",
        "facebook.com/share",
        "instagram.com/reel",
        "tiktok.com",
        "twitter.com",
        "x.com",
    ]

    def __init__(self) -> None:
        """Initialize the video scraping service."""
        self.file_cache = FileCacheService()
        self.ytdlp_extractor = YtDlpExtractor()
        self.transcriber = AudioTranscriber()

    async def is_video_url(self, url: "HttpUrl | str") -> bool:
        """Check if the provided URL is from a supported video platform."""
        url_str = str(url).lower()

        for pattern in self.VIDEO_PLATFORM_PATTERNS:
            if pattern.lower() in url_str:
                self.logger.info(f"Detected video platform: {pattern}")
                return True

        self.logger.info(f"URL does not match any supported video platforms: {url}")
        return False

    async def fetch_metadata(self, url: str) -> ExtractionData:
        """Return video metadata, without downloading audio.

        Cached under the ``metadata`` artifact so repeated questions about one video
        cost one yt-dlp call, not one per turn.
        """
        cached = await self.file_cache.get_artifact(url, "metadata")
        if cached is not None:
            try:
                return ExtractionData(**cached)
            except Exception as e:
                self.logger.warning(f"Cached metadata for {url} is unreadable: {e}")

        async with self.file_cache.artifact_lock(url, "metadata"):
            # Re-check under the lock: another turn may have written the metadata
            # (or a full transcript) while we waited.
            cached = await self.file_cache.get_artifact(url, "metadata")
            if cached is not None:
                try:
                    return ExtractionData(**cached)
                except Exception:  # noqa: BLE001 - unreadable entry, fall through and re-extract
                    pass

            extraction_data = await self.ytdlp_extractor.extract_metadata(url)
            await self._write_metadata_merged(url, extraction_data.model_dump(mode="json"))
            return extraction_data

    async def _write_metadata_merged(self, url: str, updates: dict[str, Any]) -> None:
        """Merge ``updates`` into the video's ``metadata`` artifact and write it.

        Caller must hold ``file_cache.artifact_lock(url, "metadata")``. Merges rather
        than overwrites, so a concurrent transcript or summary write on the same URL
        is never clobbered: ``summaries`` is merged entry by entry, and a ``None`` in
        ``updates`` (e.g. the ``transcript`` field of a metadata-only extraction) never
        overwrites an existing value. ``audio_path`` points at a temp file that is
        already gone, so it is never persisted.
        """
        current = await self.file_cache.get_artifact(url, "metadata") or {}
        merged: dict[str, Any] = {**current, **{k: v for k, v in updates.items() if v is not None}}
        merged["summaries"] = {
            **current.get("summaries", {}),
            **updates.get("summaries", {}),
        }
        merged.pop("audio_path", None)
        await self.file_cache.put_artifact(url, "metadata", merged)

    async def store_summary(self, url: str, key: str, summary: str) -> None:
        """Persist one summary variant into the video's ``metadata`` artifact.

        Takes the artifact lock and merges, so two concurrent ``summarize`` calls for
        different ``style:length`` keys on the same URL both survive.
        """
        async with self.file_cache.artifact_lock(url, "metadata"):
            await self._write_metadata_merged(url, {"summaries": {key: summary}})

    async def fetch_transcript(self, url: str) -> StoredTranscript:
        """Return the video's transcript, transcribing it only if not already stored.

        The transcript lives in the ``metadata`` artifact and is written the instant
        transcription succeeds -- before any analysis or summarization runs -- so a
        later failure never costs a second Whisper call. Metadata already on that
        artifact is reused rather than re-resolved, so a turn that asked about the
        video first does not pay for a second yt-dlp round trip here.

        Raises:
            VideoScrapingError: If the video has no usable audio track.
        """
        meta = await self.file_cache.get_artifact(url, "metadata")
        stored = self._transcript_from_meta(meta)
        if stored is not None:
            self.logger.info(f"Reusing stored transcript for URL: {url}")
            return stored

        async with self.file_cache.artifact_lock(url, "metadata"):
            # Double-checked: a concurrent turn for this URL may have transcribed it
            # while we waited. The lock is held across extraction + Whisper so two
            # turns never run transcription on the same video -- an asyncio.Lock is
            # cooperative, so this only makes same-URL callers wait, not the loop.
            meta = await self.file_cache.get_artifact(url, "metadata")
            stored = self._transcript_from_meta(meta)
            if stored is not None:
                self.logger.info(f"Reusing stored transcript for URL: {url}")
                return stored

            extraction_data = self._extraction_from_meta(meta)
            if extraction_data is None:
                extraction_data = await self.ytdlp_extractor.extract_metadata(url)

            audio_path = await self.ytdlp_extractor.fetch_audio(
                url,
                video_id=str(extraction_data.metadata.get("video_id") or ""),
                duration=extraction_data.duration,
            )
            if audio_path is None or not audio_path.exists():
                raise VideoScrapingError(
                    "No audio track is available for this video, so it cannot be transcribed."
                )

            transcript = await self.transcriber.transcribe(audio_path)
            await self._persist_transcript(url, transcript, extraction_data)
            return transcript

    @staticmethod
    def _extraction_from_meta(meta: Optional[dict[str, Any]]) -> Optional[ExtractionData]:
        """Reconstruct already-resolved metadata from a cached ``metadata`` artifact."""
        if not meta:
            return None
        try:
            return ExtractionData(**meta)
        except Exception:  # noqa: BLE001 - a corrupt cache entry is a miss, not an error
            return None

    @staticmethod
    def _transcript_from_meta(meta: Optional[dict[str, Any]]) -> Optional[StoredTranscript]:
        """Reconstruct a stored transcript from a cached ``metadata`` artifact."""
        if not meta or not meta.get("transcript"):
            return None
        try:
            return StoredTranscript(**meta["transcript"])
        except Exception:  # noqa: BLE001 - a corrupt cache entry is a miss, not an error
            return None

    async def _persist_transcript(
        self,
        url: str,
        transcript: StoredTranscript,
        extraction_data: ExtractionData,
    ) -> None:
        """Merge the transcript into the video's ``metadata`` artifact.

        Caller must hold ``file_cache.artifact_lock(url, "metadata")``. Seeds the entry
        from the freshly extracted metadata (title/author) and merges in the
        transcript, keeping any ``summaries`` already on the cached entry.
        """
        updates = extraction_data.model_dump(mode="json")
        updates["transcript"] = transcript.model_dump(mode="json")
        await self._write_metadata_merged(url, updates)
