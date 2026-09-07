"""Video scraping service for extracting content from video URLs.

The pipeline is decomposed into three independently callable, independently cached
stages -- metadata, transcript, analysis -- because the agentic flow needs them one at
a time (answering "what is this video?" must not download audio) and because each
must be cached the moment it succeeds. Caching only the final assembled blob meant a
failure in the cheap analysis step discarded the expensive Whisper run.

The transcript is persisted *inside* the ``metadata`` cache artifact -- one file per
video holds its title/author, its cached summaries, and its transcript -- because none
of that goes stale and re-running Whisper is the most expensive operation here. The
``metadata`` artifact therefore keeps the long ``transcript_ttl`` (see
``services/storage/file_cache.py``).

``process_video`` composes the three into the ``VideoContent`` the fixed
``POST /api/v1/process/url`` endpoint returns; its observable behaviour is unchanged.
"""

import json
from typing import Any, Optional

from pydantic import HttpUrl

from webtonotion.config.logging import LoggerMixin
from webtonotion.exceptions import VideoScrapingError
from webtonotion.models.transcript import StoredTranscript
from webtonotion.models.video import ContentAnalysisResult, VideoContent
from webtonotion.services.analysis.content_analyzer import ContentAnalyzer
from webtonotion.services.analysis.transcriber import AudioTranscriber
from webtonotion.services.extraction.base import ExtractionData
from webtonotion.services.extraction.ytdlp_extractor import YtDlpExtractor
from webtonotion.services.storage.file_cache import FileCacheService


class VideoScrapingService(LoggerMixin):
    """Extracts, transcribes, and analyses video content, stage by stage."""

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
        self.analyzer = ContentAnalyzer()

    async def is_video_url(self, url: HttpUrl) -> bool:
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

            extraction_data = await self.ytdlp_extractor.extract(url, download_audio=False)
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
        later failure never costs a second Whisper call.

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

            extraction_data = await self.ytdlp_extractor.extract(url, download_audio=True)
            if not extraction_data.audio_path or not extraction_data.audio_path.exists():
                raise VideoScrapingError(
                    "No audio track is available for this video, so it cannot be transcribed."
                )

            transcript = await self.transcriber.transcribe(extraction_data.audio_path)
            await self._persist_transcript(url, transcript, extraction_data)
            return transcript

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

    async def analyze_content(
        self, url: str, extraction_data: ExtractionData, transcript_text: str
    ) -> ContentAnalysisResult:
        """Run topic/sentiment/location analysis, cached under the ``analysis`` artifact."""
        cached = await self.file_cache.get_artifact(url, "analysis")
        if cached is not None:
            try:
                return ContentAnalysisResult(**cached)
            except Exception as e:
                self.logger.warning(f"Cached analysis for {url} is unreadable: {e}")

        info_for_analysis = {
            "title": extraction_data.title,
            "description": extraction_data.description,
            "extractor": extraction_data.metadata.get("platform", "unknown"),
        }
        analyzed = await self.analyzer.analyze(info_for_analysis, transcript_text)
        await self.file_cache.put_artifact(url, "analysis", analyzed.model_dump(mode="json"))
        return analyzed

    async def process_video(self, url: HttpUrl) -> VideoContent:
        """Process a video URL and extract comprehensive content.

        Composition of the three stages above, preserving the exact behaviour the
        fixed ``/process/url`` endpoint depends on -- including that a transcription
        failure is non-fatal and simply leaves the transcript empty.

        Raises:
            VideoScrapingError: If video processing fails.
        """
        url_str = str(url)
        self.logger.info(f"Starting video processing for URL: {url_str}")

        try:
            cached_content = await self.file_cache.get_cached_content(url_str)
            if cached_content:
                return cached_content

            self.logger.info(f"Attempting yt-dlp extraction for URL: {url_str}")
            extraction_data = await self.ytdlp_extractor.extract(url_str, download_audio=True)
            self.logger.info(f"Successfully extracted content with yt-dlp for URL: {url_str}")

            transcript_text = await self._transcribe_if_possible(url_str, extraction_data)

            analyzed_content = await self.analyze_content(url_str, extraction_data, transcript_text)

            video_content = VideoContent(
                url=url,
                title=extraction_data.title,
                description=extraction_data.description,
                author=extraction_data.author,
                duration=extraction_data.duration,
                published_at=extraction_data.published_at,
                transcript=transcript_text,
                topics=analyzed_content.topics,
                sentiment=analyzed_content.sentiment,
                locations=analyzed_content.locations,
                metadata={
                    **extraction_data.metadata,
                    "key_insights": json.dumps(analyzed_content.key_insights),
                    "content_category": analyzed_content.content_category,
                    **(
                        {"skipped_transcription": "duration_exceeded"}
                        if (
                            extraction_data.duration
                            and extraction_data.duration > self.ytdlp_extractor.max_audio_duration
                            and not transcript_text
                        )
                        else {}
                    ),
                },
            )

            await self.file_cache.cache_content(url_str, video_content)
            return video_content

        except Exception as e:
            self.logger.error(f"Video processing failed for URL {url_str}: {e}", exc_info=True)
            raise VideoScrapingError(f"Failed to process video: {e}") from e

    async def _transcribe_if_possible(self, url: str, extraction_data: ExtractionData) -> str:
        """Transcribe the extracted audio, returning "" rather than failing the request.

        A transcription error is non-fatal here by design (pinned by the
        characterization tests): a video whose audio Whisper choked on still yields a
        page from its metadata. Persisting the transcript and writing the debug
        transcript file are both best-effort once transcription itself has succeeded --
        matching the pre-refactor behavior, where a downstream write failure after a
        successful transcription was logged but never discarded the already-obtained
        transcript or failed the request.
        """
        if not extraction_data.audio_path or not extraction_data.audio_path.exists():
            return ""

        try:
            transcript = await self.transcriber.transcribe(extraction_data.audio_path)
        except Exception as e:
            self.logger.warning(f"Transcription failed for {url}: {e}")
            # Audio path cleanup is handled by transcriber on error.
            return ""

        try:
            async with self.file_cache.artifact_lock(url, "metadata"):
                await self._persist_transcript(url, transcript, extraction_data)
        except Exception as e:
            self.logger.warning(f"Failed to persist transcript for {url}: {e}")

        video_id = extraction_data.metadata.get("video_id")
        if video_id:
            try:
                transcript_file = self.transcriber.temp_dir / f"{video_id}_transcript.txt"
                transcript_file.write_text(transcript.text, encoding="utf-8")
                self.logger.debug(f"Saved transcription to {transcript_file}")
            except Exception as e:
                self.logger.warning(f"Failed to write transcript debug file for {url}: {e}")

        return transcript.text
