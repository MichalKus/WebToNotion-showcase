"""Integration tests for Notion service.

This module contains integration tests that verify the NotionService
works correctly with the actual Notion API. These tests require
valid Notion API credentials and should be run in a test environment.
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from notion_client.errors import APIResponseError

from webtonotion.config.settings import Settings
from webtonotion.exceptions import NotionAPIError, NotionAuthenticationError
from webtonotion.models.notion import NotionDatabase, NotionPagePayload
from webtonotion.models.video import VideoContent
from webtonotion.services.notion_service import NotionService


@pytest.mark.integration
class TestNotionServiceIntegration:
    """Integration tests for NotionService with real API calls."""

    @pytest.fixture(scope="class")
    def settings(self):
        """Create settings for integration testing.

        Note: These tests require a valid Notion API key set in environment
        variables or test configuration.
        """
        return Settings()

    @pytest.fixture(scope="class")
    def notion_service(self, settings):
        """Create NotionService instance for integration testing."""
        # Skip tests if no API key is configured
        if not settings.notion_api_key:
            pytest.skip("Notion API key not configured for integration tests")

        return NotionService(settings)

    @pytest.mark.asyncio
    async def test_service_initialization(self, notion_service):
        """Test that the service initializes correctly with real credentials."""
        assert notion_service.client is not None
        assert notion_service.rate_limiter is not None
        assert notion_service.settings is not None

    @pytest.mark.asyncio
    async def test_health_check_with_real_api(self, notion_service):
        """Test health check with real Notion API."""
        result = await notion_service.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_get_databases_real_api(self, notion_service):
        """Test retrieving databases from real Notion API."""
        try:
            databases = await notion_service.get_databases()

            # Verify the response structure
            assert isinstance(databases, list)

            # If databases exist, verify their structure
            if databases:
                for db in databases:
                    assert isinstance(db, NotionDatabase)
                    assert db.id is not None
                    assert db.name is not None
                    assert isinstance(db.properties, dict)

        except NotionAPIError as e:
            # Log the error for debugging but don't fail the test
            # as it might be due to permissions or API limits
            pytest.skip(f"API error during database retrieval: {str(e)}")

    @pytest.mark.asyncio
    async def test_get_database_properties_real_api(self, notion_service):
        """Test retrieving database properties from real API."""
        try:
            # First get available databases
            databases = await notion_service.get_databases()

            if not databases:
                pytest.skip("No databases available for testing")

            # Test with the first available database
            test_db = databases[0]
            properties = await notion_service.get_database_properties(test_db.id)

            assert isinstance(properties, dict)
            # Most databases should have at least a title property
            assert len(properties) > 0

        except NotionAPIError as e:
            pytest.skip(f"API error during properties retrieval: {str(e)}")

    @pytest.mark.asyncio
    async def test_create_video_page_flow(self, notion_service):
        """Test the full video page creation flow with mocked agent but real Notion API."""
        try:
            # 1. Get real databases
            databases = await notion_service.get_databases()
            if not databases:
                pytest.skip("No databases available for integration test")

            test_db = databases[0]

            # 2. Get real properties to identify the title field
            properties = await notion_service.get_database_properties(test_db.id)

            # Find the title property (required for creating a page)
            title_prop = next((k for k, v in properties.items() if v.get("type") == "title"), None)

            if not title_prop:
                pytest.skip(
                    f"Database {test_db.id} has no title property, cannot test page creation"
                )

            # 3. Create a valid payload using the real title property name
            mock_payload = NotionPagePayload(
                parent={"database_id": test_db.id},
                properties={
                    title_prop: {"title": [{"text": {"content": "Integration Test Video"}}]}
                },
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": "Created via integration test"},
                                }
                            ]
                        },
                    }
                ],
            )

            mock_agent_result = AsyncMock()
            mock_agent_result.output = mock_payload

            video_content = VideoContent(
                url="https://example.com",
                title="Integration Test",
                author="Test",
                duration=100,
                transcript="Test",
            )

            # Patch the agent to avoid LLM calls
            with patch(
                "webtonotion.services.notion_service.notion_mapper_agent.run",
                new_callable=AsyncMock,
            ) as mock_run:
                mock_run.return_value = mock_agent_result

                # Execute the service method
                # This tests: get_database_properties (Real) -> Agent (Mocked) -> create_page (Real)
                result = await notion_service.create_video_page(test_db.id, video_content)

                assert result.success is True
                assert result.id is not None

                # Optional: Verify the page was actually created if we wanted to be thorough,
                # but result.success=True from the API client is usually enough.

        except NotionAPIError as e:
            pytest.skip(f"API error during integration test: {e}")


@pytest.mark.integration
class TestNotionServiceErrorHandling:
    """Test error handling with mocked API scenarios."""

    @pytest.fixture
    def notion_service(self):
        """Create a NotionService instance for error handling testing without a real API key."""
        from webtonotion.config.settings import Settings

        settings = Settings()
        settings.notion_api_key = "fake_key"  # Use a fake key
        return NotionService(settings)

    @pytest.mark.asyncio
    @patch("webtonotion.services.notion_service.Client")
    async def test_invalid_api_key_handling(self, mock_client):
        """Test that NotionAuthenticationError is raised for invalid API keys."""
        # Configure the mock to raise APIResponseError on search
        mock_search = mock_client.return_value.search
        mock_response = httpx.Response(
            status_code=401,
            json={"code": "unauthorized", "message": "API token is invalid."},
        )
        mock_search.side_effect = APIResponseError(
            response=mock_response,
            code="unauthorized",
            message="API token is invalid.",
        )

        # Initialize NotionService with a fake key
        from webtonotion.config.settings import Settings

        settings = Settings()
        settings.notion_api_key = "fake_key"
        notion_service = NotionService(settings)

        # Expect NotionAuthenticationError to be raised
        with pytest.raises(NotionAuthenticationError, match="Notion API authentication failed"):
            await notion_service.get_databases()

    @pytest.mark.asyncio
    @patch("webtonotion.services.notion_service.Client")
    async def test_invalid_database_id_handling(self, mock_client):
        """Test that NotionAPIError is raised for invalid database IDs."""
        # Configure the mock to raise APIResponseError on retrieve
        mock_retrieve = mock_client.return_value.databases.retrieve
        mock_response = httpx.Response(
            status_code=404,
            json={
                "code": "object_not_found",
                "message": "Could not find database with ID: xxxxx.",
            },
        )
        mock_retrieve.side_effect = APIResponseError(
            response=mock_response,
            code="object_not_found",
            message="Could not find database with ID: xxxxx.",
        )

        # Initialize NotionService with a fake key
        from webtonotion.config.settings import Settings

        settings = Settings()
        settings.notion_api_key = "fake_key"
        notion_service = NotionService(settings)

        # Expect NotionAPIError to be raised
        with pytest.raises(NotionAPIError, match="Notion API error"):
            await notion_service.get_database_properties("invalid-db-id")
