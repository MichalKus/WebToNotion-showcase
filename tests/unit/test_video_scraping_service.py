"""Characterization tests for VideoScrapingService.process_video.

These tests pin the service's *current* observable behaviour -- including
quirks -- so the agentic orchestrator refactor
(docs/superpowers/specs/2026-08-17-agentic-orchestrator-design.md) can be
shown to preserve it. They are not aspirational: where behaviour looks
wrong, it is pinned as-is with a comment pointing at what changes it.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import HttpUrl

from webtonotion.exceptions import VideoScrapingError
from webtonotion.models.video import ContentAnalysisResult, VideoContent
from webtonotion.services.extraction.base import ExtractionData
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

    All four collaborators listed in the plan (YtDlpExtractor, AudioTranscriber,
    ContentAnalyzer, FileCacheService) are patched at construction time so the
    real constructors -- which read settings like OPENROUTER_API_KEY -- never run.
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

    service.ytdlp_extractor = MagicMock()
    service.ytdlp_extractor.extract = AsyncMock(return_value=make_extraction_data())
    service.ytdlp_extractor.max_audio_duration = 900

    service.transcriber = MagicMock()
    service.transcriber.transcribe = AsyncMock(return_value="")
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
        service.transcriber.transcribe = AsyncMock(return_value="hello world")
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
