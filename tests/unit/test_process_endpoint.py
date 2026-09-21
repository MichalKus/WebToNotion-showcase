"""Characterization tests for POST /api/v1/process/url.

This module pins the contract between service-layer exceptions and HTTP
status codes in `api/process.py`. The endpoint is now re-pointed at the
shared write path (`webtonotion.agents.writer`), so these tests stub the
two writer functions where the handler looks them up
(`webtonotion.api.process.build_page_content` /
`webtonotion.api.process.write_video_page`) rather than the legacy
`video_service.process_video` / `notion_service.create_video_page`.

`_validate_request_and_get_db_schema` still calls
`notion_service.get_database_properties` and `video_service.is_video_url`,
so those service mocks stay.

The process router is mounted on its own, without the auth/rate-limit
dependencies main.py attaches at include_router time -- those are exercised
separately in test_dependencies.py.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webtonotion.api.process import router as process_router
from webtonotion.dependencies import get_notion_service, get_video_scraping_service
from webtonotion.exceptions import (
    ContentProcessingError,
    NotionAPIError,
    NotionAuthenticationError,
    VideoScrapingError,
    WebToNotionError,
)
from webtonotion.models.chat import SaveResult
from webtonotion.models.video import VideoPageContent


def build_client(notion_service, video_service) -> TestClient:
    """Mount the process router with the two service dependencies overridden."""
    app = FastAPI()
    app.include_router(process_router, prefix="/api/v1")
    app.dependency_overrides[get_notion_service] = lambda: notion_service
    app.dependency_overrides[get_video_scraping_service] = lambda: video_service
    return TestClient(app)


def make_notion_service(**overrides) -> AsyncMock:
    service = AsyncMock()
    service.get_database_properties.return_value = {"Name": {"type": "title"}}
    for key, value in overrides.items():
        getattr(service, key).side_effect = value
    return service


def make_video_service(**overrides) -> AsyncMock:
    service = AsyncMock()
    service.is_video_url.return_value = True
    for key, value in overrides.items():
        getattr(service, key).side_effect = value
    return service


CONTENT = VideoPageContent(
    url="https://www.youtube.com/watch?v=abc123",
    title="Test Video",
    author="Test Author",
    duration=120.0,
    platform="youtube",
    language="en",
    summary="a summary",
    transcript_excerpt="hello world",
)

RESULT = SaveResult(
    page_id="page_id",
    page_url="https://notion.so/page_id",
    database_id="db_id",
    title="Test Video",
)


@pytest.fixture
def writer():
    """Patch the two writer functions where the handler imports them."""
    with (
        patch(
            "webtonotion.api.process.build_page_content",
            new=AsyncMock(return_value=CONTENT),
        ) as bpc,
        patch(
            "webtonotion.api.process.write_video_page",
            new=AsyncMock(return_value=RESULT),
        ) as wvp,
    ):
        yield SimpleNamespace(build_page_content=bpc, write_video_page=wvp)


VALID_PAYLOAD = {
    "url": "https://www.youtube.com/watch?v=abc123",
    "database_id": "db_id",
}


class TestProcessUrlStatusContract:
    def test_happy_path_returns_200_with_success_response_shape(self, writer):
        client = build_client(make_notion_service(), make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["page_id"] == "page_id"
        assert body["page_url"] == "https://notion.so/page_id"
        assert body["content_type"] == "video"
        assert body["video_details"]["title"] == "Test Video"
        assert body["video_details"]["platform"] == "youtube"
        assert body["video_details"]["language"] == "en"
        assert body["video_details"]["transcript_length"] == len("hello world")
        assert body["video_details"]["summary_length"] == len("a summary")
        assert "topics" not in body["video_details"]
        assert "sentiment" not in body["video_details"]
        assert body["processing_stats"]["transcription_available"] is True

    def test_missing_database_id_returns_400(self, writer):
        client = build_client(make_notion_service(), make_video_service())

        response = client.post(
            "/api/v1/process/url", json={"url": "https://www.youtube.com/watch?v=abc123"}
        )

        assert response.status_code == 400

    def test_non_video_url_returns_400(self, writer):
        video_service = make_video_service()
        video_service.is_video_url.return_value = False
        client = build_client(make_notion_service(), video_service)

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 400

    def test_video_scraping_error_returns_422(self, writer):
        writer.build_page_content.side_effect = VideoScrapingError("extraction failed")
        client = build_client(make_notion_service(), make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 422

    def test_notion_authentication_error_returns_401(self, writer):
        notion_service = make_notion_service(
            get_database_properties=NotionAuthenticationError("bad key")
        )
        client = build_client(notion_service, make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 401

    def test_notion_api_error_returns_503(self, writer):
        writer.write_video_page.side_effect = NotionAPIError("boom", status_code=500)
        client = build_client(make_notion_service(), make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 503

    def test_web_to_notion_error_returns_500(self, writer):
        notion_service = make_notion_service(
            get_database_properties=WebToNotionError("generic app error")
        )
        client = build_client(notion_service, make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 500

    def test_unexpected_exception_returns_500_without_leaking_message(self, writer):
        notion_service = make_notion_service(
            get_database_properties=Exception("secret internal stack trace details")
        )
        client = build_client(notion_service, make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 500
        assert "secret internal stack trace details" not in response.text
        assert response.json()["detail"] == "An unexpected error occurred while processing the URL"

    def test_content_processing_error_returns_500(self, writer):
        writer.write_video_page.side_effect = ContentProcessingError("mapper down")
        client = build_client(make_notion_service(), make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 500
