"""AudioTranscriber returns a structured StoredTranscript with segment timestamps."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webtonotion.config.settings import settings
from webtonotion.exceptions import VideoScrapingError
from webtonotion.services.analysis.transcriber import AudioTranscriber


def make_transcriber() -> AudioTranscriber:
    with patch("webtonotion.services.analysis.transcriber.groq.AsyncGroq"):
        return AudioTranscriber()


def make_groq_response() -> MagicMock:
    response = MagicMock()
    response.text = "  hello world  "
    response.language = "en"
    response.duration = 12.5
    response.segments = [
        {"start": 0.0, "end": 6.0, "text": " hello"},
        {"start": 6.0, "end": 12.5, "text": " world"},
    ]
    return response


@pytest.mark.asyncio
async def test_structured_result_carries_text_language_and_segments(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    transcriber = make_transcriber()
    transcriber.cleanup_temp_files = False
    transcriber.groq_client.audio.transcriptions.create = AsyncMock(
        return_value=make_groq_response()
    )

    result = await transcriber.transcribe(audio)

    assert result.text == "hello world"
    assert result.language == "en"
    assert result.duration == 12.5
    assert [s.text for s in result.segments] == ["hello", "world"]
    assert result.segments[1].start == 6.0


@pytest.mark.asyncio
async def test_verbose_json_is_requested(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    transcriber = make_transcriber()
    transcriber.cleanup_temp_files = False
    create = AsyncMock(return_value=make_groq_response())
    transcriber.groq_client.audio.transcriptions.create = create

    await transcriber.transcribe(audio)

    assert create.call_args.kwargs["response_format"] == "verbose_json"


@pytest.mark.asyncio
async def test_missing_segments_yield_an_empty_segment_list(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    transcriber = make_transcriber()
    transcriber.cleanup_temp_files = False
    response = make_groq_response()
    response.segments = None
    transcriber.groq_client.audio.transcriptions.create = AsyncMock(return_value=response)

    result = await transcriber.transcribe(audio)

    assert result.segments == []
    assert result.text == "hello world"


@pytest.mark.asyncio
async def test_api_failure_still_raises_video_scraping_error(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    transcriber = make_transcriber()
    transcriber.cleanup_temp_files = False
    transcriber.groq_client.audio.transcriptions.create = AsyncMock(
        side_effect=RuntimeError("groq down")
    )

    with pytest.raises(VideoScrapingError):
        await transcriber.transcribe(audio)
