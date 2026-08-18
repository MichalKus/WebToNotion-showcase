"""Unit tests for the health check endpoints."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status

from webtonotion.api.health import notion_health_check
from webtonotion.exceptions import NotionAPIError, NotionAuthenticationError


class TestNotionHealthCheck:
    """Test cases for the /notion-health endpoint."""

    @pytest.mark.asyncio
    async def test_notion_health_check_authentication_error(self):
        """Authentication failure surfaces as 401 with the error message in the detail."""
        mock_service = Mock()
        mock_service.health_check = AsyncMock(side_effect=NotionAuthenticationError("bad key"))

        with pytest.raises(HTTPException) as exc_info:
            await notion_health_check(notion_service=mock_service)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "bad key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_notion_health_check_api_error(self):
        """API failure surfaces as 503 with the error message in the detail."""
        mock_service = Mock()
        mock_service.health_check = AsyncMock(side_effect=NotionAPIError("boom", status_code=500))

        with pytest.raises(HTTPException) as exc_info:
            await notion_health_check(notion_service=mock_service)

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "boom" in exc_info.value.detail
