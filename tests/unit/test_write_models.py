"""Unit tests for VideoPageContent and SaveResult models."""

from datetime import datetime

import pytest

from webtonotion.models.chat import SaveResult
from webtonotion.models.video import VideoPageContent


def test_video_page_content_minimal():
    """Test VideoPageContent with minimal required arguments."""
    model = VideoPageContent(
        url="https://example.com/video",
        title="Test Video",
    )
    assert str(model.url) == "https://example.com/video"
    assert model.title == "Test Video"
    assert model.author == ""
    assert model.description == ""
    assert model.duration is None
    assert model.published_at is None
    assert model.platform == "unknown"
    assert model.language is None
    assert model.summary == ""
    assert model.transcript_excerpt == ""


def test_video_page_content_with_defaults():
    """Test VideoPageContent respects provided values and defaults."""
    published = datetime(2024, 1, 1, 12, 0, 0)
    model = VideoPageContent(
        url="https://example.com/video",
        title="Test Video",
        author="John Doe",
        description="A test video",
        duration=300.5,
        published_at=published,
        platform="youtube",
        language="en",
        summary="This is a summary",
        transcript_excerpt="This is an excerpt",
    )
    assert str(model.url) == "https://example.com/video"
    assert model.title == "Test Video"
    assert model.author == "John Doe"
    assert model.description == "A test video"
    assert model.duration == 300.5
    assert model.published_at == published
    assert model.platform == "youtube"
    assert model.language == "en"
    assert model.summary == "This is a summary"
    assert model.transcript_excerpt == "This is an excerpt"


def test_video_page_content_dump_and_roundtrip():
    """Test VideoPageContent can be dumped and revalidated."""
    original = VideoPageContent(
        url="https://example.com/video",
        title="Test Video",
        author="John Doe",
        duration=300.5,
        platform="vimeo",
        summary="Test summary",
    )
    dumped = original.model_dump()
    reconstructed = VideoPageContent(**dumped)
    assert reconstructed == original
    assert reconstructed.model_dump() == dumped


def test_save_result_requires_all_fields():
    """Test SaveResult requires all four fields."""
    with pytest.raises(ValueError):
        SaveResult(
            page_id="page_123",
            page_url="https://notion.so/page_123",
            database_id="db_123",
            # title is missing
        )


def test_save_result_with_all_fields():
    """Test SaveResult with all required fields."""
    result = SaveResult(
        page_id="page_123",
        page_url="https://notion.so/page_123",
        database_id="db_123",
        title="My Saved Video",
    )
    assert result.page_id == "page_123"
    assert result.page_url == "https://notion.so/page_123"
    assert result.database_id == "db_123"
    assert result.title == "My Saved Video"


def test_save_result_dump_and_roundtrip():
    """Test SaveResult can be dumped and revalidated."""
    original = SaveResult(
        page_id="page_456",
        page_url="https://notion.so/page_456",
        database_id="db_456",
        title="Another Video",
    )
    dumped = original.model_dump()
    reconstructed = SaveResult(**dumped)
    assert reconstructed == original
    assert reconstructed.model_dump() == dumped
