"""Unit tests for the Notion service module.

This module contains comprehensive unit tests for the NotionService class,
including tests for rate limiting, database operations, page creation,
and error handling.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from notion_client.errors import APIResponseError

from webtonotion.config.settings import Settings
from webtonotion.exceptions import (
    NotionAPIError,
    NotionAuthenticationError,
    NotionRateLimitError,
)
from webtonotion.models.video import VideoContent
from webtonotion.services.notion_service import (
    NotionService,
    RateLimiter,
)


@pytest.fixture
def settings():
    """Create settings for testing."""
    return Settings(notion_api_key="test_key")


@pytest.fixture
def notion_service(settings):
    """Create NotionService instance for testing."""
    return NotionService(settings)


def create_test_service():
    """Helper function to create a NotionService instance for testing."""
    mock_settings = Mock()
    mock_settings.notion_api_key = "test_key"
    mock_settings.notion_version = "2025-09-03"
    mock_settings.openrouter_api_key = "test_openrouter_key"
    mock_settings.openrouter_model = "test_model"
    return NotionService(mock_settings)


class TestNotionService:
    """Test cases for the NotionService class."""

    def test_init_with_valid_settings(self):
        """Test NotionService initialization with valid settings."""
        mock_settings = Mock()
        mock_settings.notion_api_key = "test_api_key"
        mock_settings.notion_version = "2025-09-03"

        service = NotionService(mock_settings)

        assert service.api_key == "test_api_key"
        assert isinstance(service.rate_limiter, RateLimiter)

    def test_init_without_api_key(self):
        """Test NotionService initialization without API key raises error."""
        mock_settings = Mock()
        mock_settings.notion_api_key = None
        mock_settings.notion_version = "2025-09-03"

        with pytest.raises(NotionAuthenticationError, match="Notion API key is required"):
            NotionService(mock_settings)

    @pytest.mark.asyncio
    async def test_get_databases_success(self):
        """Test successful database retrieval."""
        service = create_test_service()

        # Mock the client response
        mock_response = {
            "results": [
                {
                    "id": "db1",
                    "title": [{"plain_text": "Test Database"}],
                    "properties": {"Name": {"type": "title"}},
                    "created_time": "2023-01-01T00:00:00.000Z",
                    "last_edited_time": "2023-01-01T00:00:00.000Z",
                    "url": "https://notion.so/db1",
                }
            ]
        }

        with patch.object(service.client, "search") as mock_search:
            mock_search.return_value = mock_response

            databases = await service.get_databases()

            assert len(databases) == 1
            assert databases[0].id == "db1"
            assert databases[0].name == "Test Database"

    @pytest.mark.asyncio
    async def test_get_databases_api_error(self):
        """Test database retrieval with API error."""
        service = create_test_service()

        with patch.object(service.client, "search") as mock_search:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.headers = {}
            mock_error = APIResponseError(
                response=mock_response,
                message="Invalid request",
                code="validation_error",
            )
            mock_search.side_effect = mock_error

            with pytest.raises(NotionAPIError):
                await service.get_databases()

    @pytest.mark.asyncio
    async def test_get_databases_rate_limit_error(self):
        """Test database retrieval with rate limit error."""
        service = create_test_service()

        with patch.object(service.client, "search") as mock_search:
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.headers = {}
            mock_error = APIResponseError(
                response=mock_response,
                message="Rate limit exceeded",
                code="rate_limited",
            )
            mock_search.side_effect = mock_error

            with pytest.raises(NotionRateLimitError):
                await service.get_databases()

    @pytest.mark.asyncio
    async def test_create_page_success(self):
        """Test successful page creation."""
        service = create_test_service()

        # Test data
        database_id = "test_db_id"
        properties = {"Title": {"title": [{"text": {"content": "Test Page"}}]}}
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": "Test paragraph"}}]
                },
            },
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Test heading"}}]},
            },
        ]

        # Mock response that matches the actual API response structure
        mock_response = {
            "id": "page_id",
            "created_time": "2023-01-01T00:00:00Z",
            "last_edited_time": "2023-01-01T00:00:00Z",
            "url": "https://notion.so/page_id",
            "properties": properties,
            "archived": False,
        }

        with patch.object(service.client.pages, "create") as mock_create:
            mock_create.return_value = mock_response

            result = await service.create_page(database_id, properties, children)

            # Verify the result is a NotionPageResponse object
            assert result.id == "page_id"
            assert result.url == "https://notion.so/page_id"
            assert result.success is True
            assert result.message == "Page created successfully"

            # Verify the API call
            mock_create.assert_called_once()
            call_args = mock_create.call_args[1]
            assert call_args["parent"]["database_id"] == database_id
            assert call_args["properties"] == properties
            assert call_args["children"] == children

    @pytest.mark.asyncio
    async def test_create_video_page_success(self):
        """Test successful video page creation using the agent."""
        service = create_test_service()

        # Test data
        database_id = "test_db_id"
        video_content = VideoContent(
            url="https://example.com",
            title="Test Video",
            author="Test Author",
            duration=120,
            published_at=datetime(2023, 1, 1),
            transcript="Test transcript",
            topics=["test"],
            sentiment="positive",
        )

        # Mock database schema
        db_schema = {"Name": {"type": "title"}, "URL": {"type": "url"}}

        # Mock agent response
        agent_output_json = json.dumps(
            {
                "parent": {"database_id": database_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": "Test Video"}}]},
                    "URL": {"url": "https://example.com"},
                },
                "children": [],
            }
        )

        mock_agent_result = Mock()
        mock_agent_result.output = agent_output_json

        # Mock create_page response
        mock_page_response = Mock()
        mock_page_response.id = "new_page_id"
        mock_page_response.success = True

        # Patch the dependencies
        with (
            patch(
                "webtonotion.services.notion_service.notion_mapper_agent.run",
                new_callable=AsyncMock,
            ) as mock_agent_run,
            patch.object(
                service, "get_database_properties", new_callable=AsyncMock
            ) as mock_get_props,
            patch.object(service, "create_page", new_callable=AsyncMock) as mock_create_page,
        ):

            mock_get_props.return_value = db_schema
            mock_agent_run.return_value = mock_agent_result
            mock_create_page.return_value = mock_page_response

            result = await service.create_video_page(database_id, video_content)

            assert result == mock_page_response

            # Verify interactions
            mock_get_props.assert_called_once_with(database_id)
            mock_agent_run.assert_called_once()
            mock_create_page.assert_called_once()

            # Verify create_page was called with correct data
            call_args = mock_create_page.call_args
            assert call_args[1]["database_id"] == database_id
            assert "Name" in call_args[1]["properties"]

    @pytest.mark.asyncio
    async def test_create_video_page_agent_invalid_json(self):
        """Test video page creation when agent returns invalid JSON."""
        service = create_test_service()

        video_content = VideoContent(
            url="https://example.com", title="Test", author="Test", duration=0, transcript=""
        )

        # Mock agent returning invalid JSON
        mock_agent_result = Mock()
        mock_agent_result.output = "Invalid JSON"

        with (
            patch(
                "webtonotion.services.notion_service.notion_mapper_agent.run",
                new_callable=AsyncMock,
            ) as mock_agent_run,
            patch.object(
                service, "get_database_properties", new_callable=AsyncMock
            ) as mock_get_props,
        ):

            mock_get_props.return_value = {}
            mock_agent_run.return_value = mock_agent_result

            # Should raise NotionAPIError (wrapping the ValueError from JSON parsing)
            with pytest.raises(NotionAPIError):
                await service.create_video_page("db_id", video_content)
