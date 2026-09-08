"""Contract tests for the transcript and video-tool models added in PR 2."""

from webtonotion.config.settings import Settings
from webtonotion.models.transcript import StoredTranscript, TranscriptRef, TranscriptSegment


def test_stored_transcript_defaults_to_empty_segments():
    stored = StoredTranscript(text="hello world")
    assert stored.segments == []
    assert stored.language is None
    assert stored.duration is None


def test_transcript_segment_round_trips_through_json():
    segment = TranscriptSegment(start=0.0, end=2.5, text="hello")
    assert TranscriptSegment.model_validate_json(segment.model_dump_json()) == segment


def test_transcript_ref_carries_a_preview_not_the_body():
    ref = TranscriptRef(
        url="https://example.com/v",
        transcript_hash="abc",
        char_count=50000,
        segment_count=400,
        duration=1800.0,
        language="en",
        preview="first words...",
    )
    assert ref.char_count == 50000
    assert len(ref.preview) < 100


def test_transcript_ref_from_transcript_builds_a_chat_sized_handle():
    stored = StoredTranscript(
        text="abcdefghij",
        language="en",
        duration=12.5,
        segments=[
            TranscriptSegment(start=0.0, end=6.0, text="abcde"),
            TranscriptSegment(start=6.0, end=12.5, text="fghij"),
        ],
    )

    ref = TranscriptRef.from_transcript("https://example.com/v", stored, preview_chars=5)

    assert ref.url == "https://example.com/v"
    assert ref.char_count == 10
    assert ref.segment_count == 2
    assert ref.language == "en"
    assert ref.duration == 12.5
    assert ref.preview == "abcde"
    assert len(ref.transcript_hash) == 64


def test_settings_expose_pr2_transcript_defaults():
    settings = Settings()
    assert settings.transcript_preview_chars == 500
    assert settings.summary_map_reduce_threshold_chars == 120_000
    assert settings.summary_map_reduce_window_chars == 20_000
    assert settings.prompt_cache_ttl == "1h"


def test_summary_result_enforces_style_and_length():
    import pytest
    from pydantic import ValidationError

    from webtonotion.models.chat import SummaryResult

    valid = SummaryResult(
        url="https://example.com/v",
        style="bullet points",
        length="short",
        summary="A summary",
    )
    assert valid.style == "bullet points"
    assert valid.length == "short"

    with pytest.raises(ValidationError):
        SummaryResult(
            url="https://example.com/v",
            style="random_style",  # type: ignore[arg-type]
            length="short",
            summary="A summary",
        )

    with pytest.raises(ValidationError):
        SummaryResult(
            url="https://example.com/v",
            style="concise",
            length="infinite",  # type: ignore[arg-type]
            summary="A summary",
        )
