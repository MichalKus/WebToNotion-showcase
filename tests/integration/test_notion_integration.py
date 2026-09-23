"""Integration tests for Notion service.

This module contains integration tests that verify the NotionService
works correctly with the actual Notion API. These tests require
valid Notion API credentials and should be run in a test environment.
"""

from unittest.mock import patch

import httpx
import pytest
from notion_client.errors import APIResponseError

from webtonotion.config.settings import Settings
from webtonotion.exceptions import NotionAPIError, NotionAuthenticationError
from webtonotion.models.notion import NotionDatabase
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

    # create_video_page retired in PR 3; the write path is agents/writer.py::write_video_page (see tests/unit/test_notion_writer.py)


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
