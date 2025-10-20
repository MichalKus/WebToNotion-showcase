"""Tests for Notion property formatting functionality."""

from datetime import datetime
from unittest.mock import Mock

from webtonotion.services.notion_service import NotionService


def create_test_service():
    """Create a test NotionService instance with mock settings."""
    mock_settings = Mock()
    mock_settings.notion_api_key = "test_key"
    mock_settings.notion_version = "2025-09-03"
    return NotionService(mock_settings)


class TestFormatPropertyForNotion:
    """Test cases for the format_property_for_notion method."""

    def test_format_rich_text_property(self):
        """Test formatting rich_text property."""
        service = create_test_service()

        result = service.format_property_for_notion("rich_text", "Hello World")
        expected = {"rich_text": [{"text": {"content": "Hello World"}}]}
        assert result == expected

    def test_format_title_property(self):
        """Test formatting title property."""
        service = create_test_service()

        result = service.format_property_for_notion("title", "Page Title")
        expected = {"title": [{"text": {"content": "Page Title"}}]}
        assert result == expected

    def test_format_number_property(self):
        """Test formatting number property."""
        service = create_test_service()

        result = service.format_property_for_notion("number", 42)
        expected = {"number": 42}
        assert result == expected

    def test_format_url_property(self):
        """Test formatting url property."""
        service = create_test_service()

        result = service.format_property_for_notion("url", "https://example.com")
        expected = {"url": "https://example.com"}
        assert result == expected

    def test_format_email_property(self):
        """Test formatting email property."""
        service = create_test_service()

        result = service.format_property_for_notion("email", "test@example.com")
        expected = {"email": "test@example.com"}
        assert result == expected

    def test_format_phone_number_property(self):
        """Test formatting phone_number property."""
        service = create_test_service()

        result = service.format_property_for_notion("phone_number", "+1234567890")
        expected = {"phone_number": "+1234567890"}
        assert result == expected

    def test_format_select_property(self):
        """Test formatting select property."""
        service = create_test_service()

        result = service.format_property_for_notion("select", "Option A")
        expected = {"select": {"name": "Option A"}}
        assert result == expected

    def test_format_multi_select_property(self):
        """Test formatting multi_select property."""
        service = create_test_service()

        result = service.format_property_for_notion("multi_select", ["Option A", "Option B"])
        expected = {"multi_select": [{"name": "Option A"}, {"name": "Option B"}]}
        assert result == expected

    def test_format_date_property_with_datetime(self):
        """Test formatting date property with datetime object."""
        service = create_test_service()
        test_date = datetime(2023, 12, 25, 10, 30, 0)

        result = service.format_property_for_notion("date", test_date)
        expected = {"date": {"start": "2023-12-25T10:30:00"}}
        assert result == expected

    def test_format_date_property_with_string(self):
        """Test formatting date property with string."""
        service = create_test_service()

        result = service.format_property_for_notion("date", "2023-12-25")
        expected = {"date": {"start": "2023-12-25"}}
        assert result == expected

    def test_format_checkbox_property(self):
        """Test formatting checkbox property."""
        service = create_test_service()

        result = service.format_property_for_notion("checkbox", True)
        expected = {"checkbox": True}
        assert result == expected

    def test_format_unsupported_property_type(self):
        """Test formatting unsupported property type falls back to rich_text."""
        service = create_test_service()

        result = service.format_property_for_notion("unsupported_type", "Some value")
        expected = {"rich_text": [{"text": {"content": "Some value"}}]}
        assert result == expected

    def test_format_long_text_truncation(self):
        """Test that long text is properly truncated."""
        service = create_test_service()
        long_text = "A" * 3000  # Text longer than 2000 characters

        result = service.format_property_for_notion("rich_text", long_text)

        # Should be truncated to 2000 characters
        assert len(result["rich_text"][0]["text"]["content"]) == 2000
        assert result["rich_text"][0]["text"]["content"] == "A" * 2000
