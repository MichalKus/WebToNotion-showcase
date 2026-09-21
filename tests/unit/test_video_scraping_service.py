"""Characterization tests for VideoScrapingService.

These tests pin the service's *current* observable behaviour -- including
quirks -- for its independently callable, independently cached stages
(``fetch_metadata``, ``fetch_transcript``, ``store_summary``). They are not
aspirational: where behaviour looks wrong, it is pinned as-is with a comment
pointing at what changes it.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webtonotion.config.settings import settings
from webtonotion.models.transcript import StoredTranscript
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


def make_service(tmp_path: Path) -> VideoScrapingService:
    """Construct a VideoScrapingService with every sub-service mocked out.

    All three collaborators (YtDlpExtractor, AudioTranscriber, FileCacheService) are
    patched at construction time so the real constructors -- which read settings like
    OPENROUTER_API_KEY -- never run. The transcript is persisted inside the
    ``metadata`` cache artifact, so there is no separate store.
    """
    with (
        patch("webtonotion.services.video_scraping_service.FileCacheService"),
        patch("webtonotion.services.video_scraping_service.YtDlpExtractor"),
        patch("webtonotion.services.video_scraping_service.AudioTranscriber"),
    ):
        service = VideoScrapingService()

    service.file_cache = MagicMock()
    service.file_cache.get_artifact = AsyncMock(return_value=None)
    service.file_cache.put_artifact = AsyncMock(return_value=None)
    # Each call hands back a fresh, uncontended lock -- enough for the single-caller
    # tests here; the concurrency tests install a shared one.
    service.file_cache.artifact_lock = MagicMock(side_effect=lambda *a, **k: asyncio.Lock())

    service.ytdlp_extractor = MagicMock()
    service.ytdlp_extractor.extract_metadata = AsyncMock(return_value=make_extraction_data())
    service.ytdlp_extractor.fetch_audio = AsyncMock(return_value=None)
    service.ytdlp_extractor.max_audio_duration = 900

    service.transcriber = MagicMock()
    service.transcriber.transcribe = AsyncMock(return_value=StoredTranscript(text=""))
    service.transcriber.temp_dir = tmp_path

    return service


class TestPipelineStages:
    """The stages tools call directly, each cached the moment it succeeds."""

    @pytest.mark.asyncio
    async def test_fetch_metadata_does_not_pull_audio(self, tmp_path):
        service = make_service(tmp_path)

        await service.fetch_metadata("https://www.example.com/watch?v=abc123")

        service.ytdlp_extractor.extract_metadata.assert_awaited_once()
        service.ytdlp_extractor.fetch_audio.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_metadata_serves_a_cached_artifact_without_calling_ytdlp(self, tmp_path):
        service = make_service(tmp_path)
        cached = make_extraction_data(title="From Cache")
        service.file_cache.get_artifact = AsyncMock(return_value=cached.model_dump(mode="json"))

        result = await service.fetch_metadata("https://www.example.com/watch?v=abc123")

        assert result.title == "From Cache"
        service.ytdlp_extractor.extract_metadata.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_transcript_stores_into_the_metadata_artifact(self, tmp_path):
        service = make_service(tmp_path)
        audio_path = tmp_path / "abc123.mp3"
        audio_path.write_bytes(b"fake audio")
        service.ytdlp_extractor.fetch_audio = AsyncMock(return_value=audio_path)
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
        service.ytdlp_extractor.extract_metadata.assert_not_called()
        service.ytdlp_extractor.fetch_audio.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_transcript_reuses_cached_metadata_instead_of_re_extracting(self, tmp_path):
        """A turn that already asked about the video paid for the yt-dlp round trip;
        transcribing it must download the audio without resolving the page again."""
        service = make_service(tmp_path)
        audio_path = tmp_path / "abc123.mp3"
        audio_path.write_bytes(b"fake audio")
        cached = make_extraction_data(title="From Cache")
        service.file_cache.get_artifact = AsyncMock(return_value=cached.model_dump(mode="json"))
        service.ytdlp_extractor.fetch_audio = AsyncMock(return_value=audio_path)

        await service.fetch_transcript("https://www.example.com/watch?v=abc123")

        service.ytdlp_extractor.extract_metadata.assert_not_called()
        assert service.ytdlp_extractor.fetch_audio.await_args.kwargs["video_id"] == "abc123"

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
        service.ytdlp_extractor.fetch_audio = AsyncMock(return_value=audio_path)

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
