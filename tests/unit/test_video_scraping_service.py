"""Characterization tests for VideoScrapingService.process_video.

These tests pin the service's *current* observable behaviour -- including
quirks -- so the agentic orchestrator refactor
(docs/superpowers/specs/2026-08-17-agentic-orchestrator-design.md) can be
shown to preserve it. They are not aspirational: where behaviour looks
wrong, it is pinned as-is with a comment pointing at what changes it.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import HttpUrl

from webtonotion.config.settings import settings
from webtonotion.exceptions import ContentProcessingError, VideoScrapingError
from webtonotion.models.transcript import StoredTranscript
from webtonotion.models.video import ContentAnalysisResult, VideoContent
from webtonotion.services.extraction.base import ExtractionData
from webtonotion.services.storage.file_cache import FileCacheService
from webtonotion.services.video_scraping_service import VideoScrapingService


def make_extraction_data(**overrides) -> ExtractionData:
    """Build an ExtractionData with sane defaults, overridable per test."""
    defaults = {
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "Test Video",
        "description": "Test description",
        "author": "Test Author",
        "duration": 120,
        "published_at": None,
        "metadata": {
            "platform": "youtube",
            "video_id": "abc123",
            "view_count": 10,
            "like_count": 1,
        },
        "audio_path": None,
    }
    defaults.update(overrides)
    return ExtractionData(**defaults)


def make_analysis_result(**overrides) -> ContentAnalysisResult:
    """Build a ContentAnalysisResult with sane defaults, overridable per test."""
    defaults = {
        "topics": ["technology"],
        "sentiment": "positive",
        "locations": ["Berlin"],
        "key_insights": ["insight one", "insight two"],
        "content_category": "tutorial",
    }
    defaults.update(overrides)
    return ContentAnalysisResult(**defaults)


def make_service(tmp_path: Path) -> VideoScrapingService:
    """Construct a VideoScrapingService with every sub-service mocked out.

    All four collaborators (YtDlpExtractor, AudioTranscriber, ContentAnalyzer,
    FileCacheService) are patched at construction time so the real constructors --
    which read settings like OPENROUTER_API_KEY -- never run. The transcript is
    persisted inside the ``metadata`` cache artifact, so there is no separate store.
    """
    with (
        patch("webtonotion.services.video_scraping_service.FileCacheService"),
        patch("webtonotion.services.video_scraping_service.YtDlpExtractor"),
        patch("webtonotion.services.video_scraping_service.AudioTranscriber"),
        patch("webtonotion.services.video_scraping_service.ContentAnalyzer"),
    ):
        service = VideoScrapingService()

    service.file_cache = MagicMock()
    service.file_cache.get_cached_content = AsyncMock(return_value=None)
    service.file_cache.cache_content = AsyncMock(return_value=None)
    service.file_cache.get_artifact = AsyncMock(return_value=None)
    service.file_cache.put_artifact = AsyncMock(return_value=None)
    # Each call hands back a fresh, uncontended lock -- enough for the single-caller
    # tests here; the concurrency tests install a shared one.
    service.file_cache.artifact_lock = MagicMock(side_effect=lambda *a, **k: asyncio.Lock())

    service.ytdlp_extractor = MagicMock()
    service.ytdlp_extractor.extract = AsyncMock(return_value=make_extraction_data())
    service.ytdlp_extractor.max_audio_duration = 900

    service.transcriber = MagicMock()
    service.transcriber.transcribe = AsyncMock(return_value=StoredTranscript(text=""))
    service.transcriber.temp_dir = tmp_path

    service.analyzer = MagicMock()
    service.analyzer.analyze = AsyncMock(return_value=make_analysis_result())

    return service


class TestProcessVideoCache:
    """Cache-hit short-circuits the whole pipeline."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_content_and_skips_extraction(self, tmp_path):
        service = make_service(tmp_path)
        cached = VideoContent(
            url=HttpUrl("https://www.youtube.com/watch?v=cached"),
            title="Cached Video",
            author="Cached Author",
            duration=42,
            transcript="cached transcript",
        )
        service.file_cache.get_cached_content = AsyncMock(return_value=cached)

        result = await service.process_video(HttpUrl("https://www.youtube.com/watch?v=cached"))

        assert result == cached
        service.ytdlp_extractor.extract.assert_not_called()


class TestProcessVideoHappyPath:
    """Full extract -> transcribe -> analyze pipeline assembles VideoContent."""

    @pytest.mark.asyncio
    async def test_happy_path_assembles_video_content_from_each_stage(self, tmp_path):
        service = make_service(tmp_path)
        audio_path = tmp_path / "abc123.mp3"
        audio_path.write_bytes(b"fake audio")
        extraction_data = make_extraction_data(audio_path=audio_path)
        service.ytdlp_extractor.extract = AsyncMock(return_value=extraction_data)
        service.transcriber.transcribe = AsyncMock(
            return_value=StoredTranscript(text="hello world")
        )
        analysis = make_analysis_result(topics=["music"], sentiment="negative", locations=["Paris"])
        service.analyzer.analyze = AsyncMock(return_value=analysis)

        result = await service.process_video(HttpUrl("https://www.youtube.com/watch?v=abc123"))

        assert result.title == extraction_data.title
        assert result.description == extraction_data.description
        assert result.author == extraction_data.author
        assert result.duration == extraction_data.duration
        assert result.transcript == "hello world"
        assert result.topics == ["music"]
        assert result.sentiment == "negative"
        assert result.locations == ["Paris"]
        service.file_cache.cache_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_audio_path_leaves_transcript_empty_but_still_analyzes(self, tmp_path):
        service = make_service(tmp_path)
        extraction_data = make_extraction_data(audio_path=None)
        service.ytdlp_extractor.extract = AsyncMock(return_value=extraction_data)

        result = await service.process_video(HttpUrl("https://www.youtube.com/watch?v=abc123"))

        assert result.transcript == ""
        service.transcriber.transcribe.assert_not_called()
        service.analyzer.analyze.assert_called_once()
        assert service.analyzer.analyze.call_args.args[1] == ""

    @pytest.mark.asyncio
    async def test_transcription_failure_is_swallowed_and_processing_continues(self, tmp_path):
        """Pins current behaviour (video_scraping_service.py:117): a transcription
        error does not fail the request, it just leaves the transcript empty."""
        service = make_service(tmp_path)
        audio_path = tmp_path / "abc123.mp3"
        audio_path.write_bytes(b"fake audio")
        extraction_data = make_extraction_data(audio_path=audio_path)
        service.ytdlp_extractor.extract = AsyncMock(return_value=extraction_data)
        service.transcriber.transcribe = AsyncMock(side_effect=Exception("transcription boom"))

        result = await service.process_video(HttpUrl("https://www.youtube.com/watch?v=abc123"))

        assert result.transcript == ""
        service.analyzer.analyze.assert_called_once()
        assert service.analyzer.analyze.call_args.args[1] == ""

    @pytest.mark.asyncio
    async def test_duration_exceeded_with_no_transcript_sets_skip_metadata(self, tmp_path):
        service = make_service(tmp_path)
        extraction_data = make_extraction_data(duration=2000, audio_path=None)
        service.ytdlp_extractor.extract = AsyncMock(return_value=extraction_data)
        service.ytdlp_extractor.max_audio_duration = 900

        result = await service.process_video(HttpUrl("https://www.youtube.com/watch?v=abc123"))

        assert result.metadata["skipped_transcription"] == "duration_exceeded"

    @pytest.mark.asyncio
    async def test_key_insights_land_in_metadata_as_json_string(self, tmp_path):
        """Pins current behaviour (video_scraping_service.py:143): key_insights is
        serialized to a JSON string in metadata rather than kept as a list."""
        service = make_service(tmp_path)
        analysis = make_analysis_result(key_insights=["first insight", "second insight"])
        service.analyzer.analyze = AsyncMock(return_value=analysis)

        result = await service.process_video(HttpUrl("https://www.youtube.com/watch?v=abc123"))

        assert result.metadata["key_insights"] == json.dumps(["first insight", "second insight"])
        assert isinstance(result.metadata["key_insights"], str)


class TestProcessVideoFailure:
    """Any unhandled failure in the pipeline is wrapped in VideoScrapingError."""

    @pytest.mark.asyncio
    async def test_extraction_failure_raises_video_scraping_error(self, tmp_path):
        service = make_service(tmp_path)
        original_error = RuntimeError("yt-dlp exploded")
        service.ytdlp_extractor.extract = AsyncMock(side_effect=original_error)

        with pytest.raises(VideoScrapingError) as exc_info:
            await service.process_video(HttpUrl("https://www.youtube.com/watch?v=abc123"))

        assert exc_info.value.__cause__ is original_error


class TestPipelineStages:
    """The stages tools call directly, each cached the moment it succeeds."""

    @pytest.mark.asyncio
    async def test_fetch_metadata_does_not_pull_audio(self, tmp_path):
        service = make_service(tmp_path)

        await service.fetch_metadata("https://www.example.com/watch?v=abc123")

        assert service.ytdlp_extractor.extract.call_args.kwargs["download_audio"] is False

    @pytest.mark.asyncio
    async def test_fetch_metadata_serves_a_cached_artifact_without_calling_ytdlp(self, tmp_path):
        service = make_service(tmp_path)
        cached = make_extraction_data(title="From Cache")
        service.file_cache.get_artifact = AsyncMock(return_value=cached.model_dump(mode="json"))

        result = await service.fetch_metadata("https://www.example.com/watch?v=abc123")

        assert result.title == "From Cache"
        service.ytdlp_extractor.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_transcript_stores_into_the_metadata_artifact(self, tmp_path):
        service = make_service(tmp_path)
        audio_path = tmp_path / "abc123.mp3"
        audio_path.write_bytes(b"fake audio")
        service.ytdlp_extractor.extract = AsyncMock(
            return_value=make_extraction_data(audio_path=audio_path)
        )
        service.transcriber.transcribe = AsyncMock(
            return_value=StoredTranscript(text="hello world")
        )

        result = await service.fetch_transcript("https://www.example.com/watch?v=abc123")

        assert result.text == "hello world"
        service.file_cache.put_artifact.assert_awaited_once()
        url_arg, artifact_arg, data_arg = service.file_cache.put_artifact.call_args.args
        assert artifact_arg == "metadata"
        assert data_arg["transcript"]["text"] == "hello world"
        assert data_arg["title"] == "Test Video"

    @pytest.mark.asyncio
    async def test_fetch_transcript_reuses_a_transcript_from_metadata(self, tmp_path):
        service = make_service(tmp_path)
        service.file_cache.get_artifact = AsyncMock(
            return_value={"title": "T", "transcript": {"text": "already stored", "segments": []}}
        )

        result = await service.fetch_transcript("https://www.example.com/watch?v=abc123")

        assert result.text == "already stored"
        service.transcriber.transcribe.assert_not_called()
        service.ytdlp_extractor.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_transcript_survives_a_failed_analysis(self, tmp_path):
        """The cache-granularity regression the spec calls out: an expensive
        transcript must not be discarded because a later, cheaper stage failed."""
        service = make_service(tmp_path)
        audio_path = tmp_path / "abc123.mp3"
        audio_path.write_bytes(b"fake audio")
        service.ytdlp_extractor.extract = AsyncMock(
            return_value=make_extraction_data(audio_path=audio_path)
        )
        service.transcriber.transcribe = AsyncMock(
            return_value=StoredTranscript(text="expensive text")
        )
        service.analyzer.analyze = AsyncMock(side_effect=ContentProcessingError("analysis down"))

        with pytest.raises(VideoScrapingError):
            await service.process_video(HttpUrl("https://www.youtube.com/watch?v=abc123"))

        metadata_writes = [
            call.args
            for call in service.file_cache.put_artifact.await_args_list
            if call.args[1] == "metadata"
        ]
        assert metadata_writes
        assert metadata_writes[-1][2]["transcript"]["text"] == "expensive text"

    @pytest.mark.asyncio
    async def test_write_metadata_merged_never_lets_none_clobber_an_existing_value(self, tmp_path):
        service = make_service(tmp_path)
        service.file_cache.get_artifact = AsyncMock(
            return_value={"transcript": {"text": "keep me", "segments": []}, "summaries": {}}
        )

        await service._write_metadata_merged(
            "https://www.example.com/watch?v=x", {"title": "New Title", "transcript": None}
        )

        saved = service.file_cache.put_artifact.call_args.args[2]
        assert saved["transcript"] == {"text": "keep me", "segments": []}
        assert saved["title"] == "New Title"


def _real_cache(tmp_path) -> FileCacheService:
    with (
        patch.object(settings, "cache_dir", str(tmp_path)),
        patch.object(settings, "enable_caching", True),
    ):
        cache = FileCacheService()
    FileCacheService._artifact_locks.clear()
    return cache


class TestMetadataArtifactConcurrency:
    """Cross-session read-modify-write of the shared 'metadata' artifact, over the
    real FileCacheService (real per-key lock, real atomic write)."""

    @pytest.mark.asyncio
    async def test_two_concurrent_fetch_transcript_calls_transcribe_once(self, tmp_path):
        service = make_service(tmp_path)
        service.file_cache = _real_cache(tmp_path)
        audio_path = tmp_path / "abc.mp3"
        audio_path.write_bytes(b"fake audio")
        service.ytdlp_extractor.extract = AsyncMock(
            return_value=make_extraction_data(audio_path=audio_path)
        )

        calls = 0

        async def slow_transcribe(_path):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return StoredTranscript(text="the body")

        service.transcriber.transcribe = AsyncMock(side_effect=slow_transcribe)

        url = "https://www.example.com/watch?v=race"
        r1, r2 = await asyncio.gather(service.fetch_transcript(url), service.fetch_transcript(url))

        assert calls == 1
        assert r1.text == r2.text == "the body"

    @pytest.mark.asyncio
    async def test_two_concurrent_store_summary_calls_keep_both_variants(self, tmp_path):
        service = make_service(tmp_path)
        service.file_cache = _real_cache(tmp_path)
        url = "https://www.example.com/watch?v=sum"
        await service.file_cache.put_artifact(
            url,
            "metadata",
            {"title": "T", "transcript": {"text": "b", "segments": []}, "summaries": {}},
        )

        await asyncio.gather(
            service.store_summary(url, "concise:medium", "S1"),
            service.store_summary(url, "bullet points:short", "S2"),
        )

        meta = await service.file_cache.get_artifact(url, "metadata")
        assert meta["summaries"] == {"concise:medium": "S1", "bullet points:short": "S2"}
        assert meta["transcript"]["text"] == "b"
