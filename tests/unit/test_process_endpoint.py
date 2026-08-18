"""Characterization tests for POST /api/v1/process/url.

This module pins the contract between service-layer exceptions and HTTP
status codes in `api/process.py`. It is the artifact the agentic
orchestrator refactor promises to keep unchanged when process/url is
re-pointed at the new tool functions
(docs/superpowers/specs/2026-08-17-agentic-orchestrator-design.md).

The process router is mounted on its own, without the auth/rate-limit
dependencies main.py attaches at include_router time -- those are exercised
separately in test_dependencies.py. This isolates the status-code contract
that belongs to process.py itself.
"""

from datetime import datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from webtonotion.api.process import router as process_router
from webtonotion.dependencies import get_notion_service, get_video_scraping_service
from webtonotion.exceptions import (
    NotionAPIError,
    NotionAuthenticationError,
    VideoScrapingError,
    WebToNotionError,
)
from webtonotion.models.notion import NotionPage, NotionPageResponse
from webtonotion.models.video import VideoContent


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
    service.create_video_page.return_value = NotionPageResponse(
        id="page_id",
        url="https://notion.so/page_id",
        created_time=datetime(2024, 1, 1),
        properties={},
        page=NotionPage(
            id="page_id",
            database_id="db_id",
            created_time=datetime(2024, 1, 1),
            last_edited_time=datetime(2024, 1, 1),
            url="https://notion.so/page_id",
        ),
        success=True,
        message="Page created successfully",
    )
    for key, value in overrides.items():
        getattr(service, key).side_effect = value
    return service


def make_video_service(**overrides) -> AsyncMock:
    service = AsyncMock()
    service.is_video_url.return_value = True
    service.process_video.return_value = VideoContent(
        url=HttpUrl("https://www.youtube.com/watch?v=abc123"),
        title="Test Video",
        author="Test Author",
        duration=120,
        transcript="hello world",
        topics=["technology"],
        sentiment="positive",
    )
    for key, value in overrides.items():
        getattr(service, key).side_effect = value
    return service


VALID_PAYLOAD = {
    "url": "https://www.youtube.com/watch?v=abc123",
    "database_id": "db_id",
}


class TestProcessUrlStatusContract:
    def test_happy_path_returns_200_with_success_response_shape(self):
        client = build_client(make_notion_service(), make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["page_id"] == "page_id"
        assert body["page_url"] == "https://notion.so/page_id"
        assert body["content_type"] == "video"
        assert body["video_details"]["title"] == "Test Video"
        assert body["processing_stats"]["transcription_available"] is True

    def test_missing_database_id_returns_400(self):
        client = build_client(make_notion_service(), make_video_service())

        response = client.post(
            "/api/v1/process/url", json={"url": "https://www.youtube.com/watch?v=abc123"}
        )

        assert response.status_code == 400

    def test_non_video_url_returns_400(self):
        video_service = make_video_service()
        video_service.is_video_url.return_value = False
        client = build_client(make_notion_service(), video_service)

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 400

    def test_video_scraping_error_returns_422(self):
        video_service = make_video_service(process_video=VideoScrapingError("extraction failed"))
        client = build_client(make_notion_service(), video_service)

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 422

    def test_notion_authentication_error_returns_401(self):
        notion_service = make_notion_service(
            get_database_properties=NotionAuthenticationError("bad key")
        )
        client = build_client(notion_service, make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 401

    def test_notion_api_error_returns_503(self):
        notion_service = make_notion_service(
            get_database_properties=NotionAPIError("boom", status_code=500)
        )
        client = build_client(notion_service, make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 503

    def test_web_to_notion_error_returns_500(self):
        notion_service = make_notion_service(
            get_database_properties=WebToNotionError("generic app error")
        )
        client = build_client(notion_service, make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 500

    def test_unexpected_exception_returns_500_without_leaking_message(self):
        notion_service = make_notion_service(
            get_database_properties=Exception("secret internal stack trace details")
        )
        client = build_client(notion_service, make_video_service())

        response = client.post("/api/v1/process/url", json=VALID_PAYLOAD)

        assert response.status_code == 500
        assert "secret internal stack trace details" not in response.text
        assert response.json()["detail"] == "An unexpected error occurred while processing the URL"
