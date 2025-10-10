"""Unit tests for the Notion service module.

This module contains comprehensive unit tests for the NotionService class,
including tests for rate limiting, database operations, page creation,
and error handling.
"""

import asyncio
import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from notion_client.errors import APIResponseError, RequestTimeoutError

from webtonotion.services.notion_service import (
    NotionService,
    RateLimiter,
)
from webtonotion.exceptions import (
    NotionServiceError,
    NotionAuthenticationError,
    NotionRateLimitError,
    NotionAPIError
)
from webtonotion.models.notion import NotionDatabase, NotionPage, NotionPageResponse
from webtonotion.config.settings import Settings


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
    from unittest.mock import Mock
    mock_settings = Mock()
    mock_settings.notion_api_key = "test_key"
    mock_settings.notion_version = "2025-09-03"
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
                    "url": "https://notion.so/db1"
                }
            ]
        }
        
        with patch.object(service.client, 'search') as mock_search:
            mock_search.return_value = mock_response
            
            databases = await service.get_databases()
            
            assert len(databases) == 1
            assert databases[0].id == "db1"
            assert databases[0].name == "Test Database"
    
    @pytest.mark.asyncio
    async def test_get_databases_api_error(self):
        """Test database retrieval with API error."""
        service = create_test_service()
        
        with patch.object(service.client, 'search') as mock_search:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.headers = {}
            mock_error = APIResponseError(
                response=mock_response,
                message="Invalid request",
                code="validation_error"
            )
            mock_search.side_effect = mock_error
            
            with pytest.raises(NotionAPIError):
                await service.get_databases()
    
    @pytest.mark.asyncio
    async def test_get_databases_rate_limit_error(self):
        """Test database retrieval with rate limit error."""
        service = create_test_service()
        
        with patch.object(service.client, 'search') as mock_search:
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.headers = {}
            mock_error = APIResponseError(
                response=mock_response,
                message="Rate limit exceeded",
                code="rate_limited"
            )
            mock_search.side_effect = mock_error
            
            with pytest.raises(NotionRateLimitError):
                await service.get_databases()
    
    @pytest.mark.asyncio
    async def test_create_page_with_children_success(self):
        """Test successful page creation with children content blocks."""
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
                }
            },
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": "Test heading"}}]
                }
            }
        ]
        
        # Mock response that matches the actual API response structure
        mock_response = {
            "id": "page_id",
            "created_time": "2023-01-01T00:00:00Z",
            "last_edited_time": "2023-01-01T00:00:00Z",
            "url": "https://notion.so/page_id",
            "properties": properties,
            "archived": False
        }
        
        with patch.object(service.client.pages, 'create') as mock_create:
            mock_create.return_value = mock_response
            
            result = await service.create_page(database_id, properties, children=children)
            
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
    async def test_create_page_api_error(self):
        """Test page creation with API error."""
        service = create_test_service()
        
        with patch.object(service.client.pages, 'create') as mock_create:
            mock_response = Mock()
            mock_response.status = 400
            mock_error = APIResponseError(
                response=mock_response,
                code="bad_request",
                message="Bad request"
            )
            mock_error.code = "bad_request"
            mock_create.side_effect = mock_error
            
            with pytest.raises(NotionAPIError):
                await service.create_page(
                    database_id="test_db",
                    properties={"title": {"title": [{"text": {"content": "Test Page"}}]}}
                )
    
    @pytest.mark.asyncio
    async def test_format_page_properties(self):
        """Test page properties formatting."""
        service = create_test_service()
        
        content = {
            "title": "Test Page",
            "url": "https://example.com",
            "description": "Test description"
        }
        
        result = service.format_page_properties(content)
        
        assert "Title" in result
        assert result["Title"]["title"][0]["text"]["content"] == "Test Page"
        assert "Url" in result
        assert result["Url"]["url"] == "https://example.com"
        assert "Description" in result
        assert result["Description"]["rich_text"][0]["text"]["content"] == "Test description"

    def test_format_page_properties_empty(self):
        """Test page properties formatting with empty content."""
        service = create_test_service()
        
        result = service.format_page_properties({})
        
        # Should return empty dict for empty input
        assert result == {}