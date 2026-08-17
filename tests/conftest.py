"""Pytest configuration and shared fixtures for WebToNotion tests.

This module provides common fixtures, markers, and configuration
for all test modules in the WebToNotion project.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import Mock, patch

import pytest
from pydantic import HttpUrl

from webtonotion.models.video import VideoContent
from webtonotion.services.video_scraping_service import VideoScrapingService


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (may require external services)"
    )
    config.addinivalue_line("markers", "slow: marks tests as slow running")
    config.addinivalue_line("markers", "requires_api_keys: marks tests that require API keys")
    config.addinivalue_line(
        "markers", "requires_internet: marks tests that require internet connection"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test names and locations."""
    for item in items:
        # Add integration marker to integration tests
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)

        # Add slow marker to tests that might be slow
        if any(
            keyword in item.name.lower() for keyword in ["transcribe", "download", "playwright"]
        ):
            item.add_marker(pytest.mark.slow)

        # Add requires_api_keys marker to tests that need API keys
        if any(keyword in item.name.lower() for keyword in ["openai", "transcribe", "analyze"]):
            item.add_marker(pytest.mark.requires_api_keys)

        # Add requires_internet marker to tests that need internet
        if any(keyword in item.name.lower() for keyword in ["youtube", "download", "extract"]):
            item.add_marker(pytest.mark.requires_internet)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_cache_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for caching during tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_openai_client():
    """Provide a mock OpenAI client for testing."""
    mock_client = Mock()
    mock_client.audio.transcriptions.create = Mock(return_value="Mock transcript")
    return mock_client


@pytest.fixture
def mock_video_info():
    """Provide mock video information from yt-dlp."""
    return {
        "id": "test_video_id",
        "title": "Test Video Title",
        "description": "Test video description with technology content",
        "uploader": "Test Channel",
        "duration": 300,  # 5 minutes
        "upload_date": "20240101",
        "view_count": 1000,
        "like_count": 50,
        "comment_count": 25,
        "extractor": "youtube",
        "webpage_url": "https://www.youtube.com/watch?v=test_video_id",
        "thumbnail": "https://img.youtube.com/vi/test_video_id/maxresdefault.jpg",
        "tags": ["technology", "tutorial", "programming"],
        "categories": ["Science & Technology"],
    }


@pytest.fixture
def mock_video_content():
    """Provide a mock VideoContent object."""
    return VideoContent(
        url=HttpUrl("https://www.youtube.com/watch?v=test_video_id"),
        title="Test Video Title",
        description="Test video description with technology content",
        author="Test Channel",
        duration=300,
        published_at=None,
        transcript="This is a test transcript about technology and programming",
        topics=["technology", "tutorial", "programming"],
        sentiment="positive",
        locations=["San Francisco", "Silicon Valley"],
        metadata={
            "platform": "youtube",
            "video_id": "test_video_id",
            "view_count": 1000,
            "like_count": 50,
            "comment_count": 25,
            "extraction_method": "ytdlp",
            "thumbnail": "https://img.youtube.com/vi/test_video_id/maxresdefault.jpg",
            "tags": ["technology", "tutorial", "programming"],
            "categories": ["Science & Technology"],
        },
    )


@pytest.fixture
def mock_long_video_info():
    """Provide mock video information for a long video."""
    return {
        "id": "long_video_id",
        "title": "Long Test Video",
        "description": "A very long video for testing duration limits",
        "uploader": "Long Content Channel",
        "duration": 1200,  # 20 minutes
        "upload_date": "20240101",
        "view_count": 5000,
        "like_count": 200,
        "extractor": "youtube",
    }


@pytest.fixture
def video_scraping_service(temp_cache_dir, mock_openai_client):
    """Provide a VideoScrapingService instance configured for testing."""
    with patch(
        "webtonotion.services.video_scraping_service.openai.AsyncOpenAI",
        return_value=mock_openai_client,
    ):
        service = VideoScrapingService()
        service.cache_dir = temp_cache_dir
        return service


@pytest.fixture
def mock_playwright_page():
    """Provide a mock Playwright page for testing."""
    mock_page = Mock()
    mock_page.goto = Mock()
    mock_page.wait_for_load_state = Mock()
    mock_page.query_selector = Mock()
    mock_page.evaluate = Mock()
    mock_page.close = Mock()
    return mock_page


@pytest.fixture
def mock_playwright_browser():
    """Provide a mock Playwright browser for testing."""
    mock_browser = Mock()
    mock_browser.new_page = Mock()
    mock_browser.close = Mock()
    return mock_browser


@pytest.fixture
def sample_urls():
    """Provide sample URLs for testing."""
    return {
        "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "youtube_short": "https://youtu.be/dQw4w9WgXcQ",
        "facebook": "https://www.facebook.com/watch/?v=123456789",
        "instagram": "https://www.instagram.com/p/ABC123/",
        "tiktok": "https://www.tiktok.com/@user/video/123456789",
        "invalid": "https://example.com/not-a-video",
        "malformed": "not-a-url-at-all",
    }


@pytest.fixture
def mock_audio_file(temp_cache_dir):
    """Provide a mock audio file for testing."""
    audio_file = temp_cache_dir / "test_audio.mp3"
    audio_file.write_text("Mock audio content")
    return audio_file


@pytest.fixture
def skip_if_no_internet():
    """Skip test if no internet connection is available."""

    def _check_internet():
        try:
            import socket

            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False

    if not _check_internet():
        pytest.skip("Test requires internet connection")


@pytest.fixture
def mock_ytdlp():
    """Provide a mock yt-dlp YoutubeDL instance."""
    mock_ytdl = Mock()
    mock_ytdl.extract_info = Mock()
    mock_ytdl.download = Mock()
    mock_ytdl.__enter__ = Mock(return_value=mock_ytdl)
    mock_ytdl.__exit__ = Mock(return_value=None)
    return mock_ytdl


@pytest.fixture
def mock_pydantic_ai_agent():
    """Provide a mock PydanticAI agent for testing."""
    mock_agent = Mock()
    mock_result = Mock()
    mock_result.data = "Topics: technology, tutorial\nSentiment: positive\nLocations: San Francisco"
    mock_agent.run = Mock(return_value=mock_result)
    return mock_agent


# Utility functions for tests


def create_test_video_content(
    url: str = "https://www.youtube.com/watch?v=test", **kwargs
) -> VideoContent:
    """Create a VideoContent instance for testing with customizable fields."""
    defaults = {
        "url": HttpUrl(url),
        "title": "Test Video",
        "description": "Test description",
        "author": "Test Author",
        "duration": 300,
        "published_at": None,
        "transcript": "Test transcript",
        "topics": ["test"],
        "sentiment": "neutral",
        "locations": [],
        "metadata": {"platform": "youtube", "extraction_method": "test"},
    }
    defaults.update(kwargs)
    return VideoContent(**defaults)


def assert_video_content_structure(content: VideoContent):
    """Assert that a VideoContent object has the expected structure."""
    assert content.url is not None
    assert isinstance(content.url, HttpUrl)
    assert content.title is not None
    assert isinstance(content.title, str)
    assert content.description is not None
    assert isinstance(content.description, str)
    assert content.author is not None
    assert isinstance(content.author, str)
    assert content.duration is not None
    assert isinstance(content.duration, int)
    assert content.duration > 0
    assert isinstance(content.topics, list)
    assert content.sentiment in ["positive", "negative", "neutral"]
    assert isinstance(content.locations, list)
    assert isinstance(content.metadata, dict)
    assert "platform" in content.metadata
