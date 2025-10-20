"""Unit tests for the Notion exception classes."""

from webtonotion.exceptions import (
    NotionAPIError,
    NotionAuthenticationError,
    NotionRateLimitError,
    NotionServiceError,
)


class TestNotionExceptions:
    """Test Notion exception classes."""

    def test_notion_authentication_error(self):
        """Test NotionAuthenticationError exception."""
        error = NotionAuthenticationError("Authentication failed")
        assert str(error) == "Authentication failed"
        assert isinstance(error, NotionServiceError)

    def test_notion_rate_limit_error(self):
        """Test NotionRateLimitError exception."""
        error = NotionRateLimitError("Rate limit exceeded")
        assert str(error) == "Rate limit exceeded"
        assert isinstance(error, NotionServiceError)

    def test_notion_api_error(self):
        """Test NotionAPIError exception with status code."""
        error = NotionAPIError(message="API error", status_code=400)
        assert str(error) == "API error"
        assert error.status_code == 400
        assert isinstance(error, NotionServiceError)

    def test_notion_api_error_minimal(self):
        """Test NotionAPIError exception with minimal parameters."""
        error = NotionAPIError()
        assert str(error) == "Unexpected Notion API error"
        assert error.status_code is None
        assert isinstance(error, NotionServiceError)
