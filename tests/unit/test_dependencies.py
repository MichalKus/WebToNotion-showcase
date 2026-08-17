"""Unit tests for dependency injection providers."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request, status

from webtonotion.config.settings import Settings
from webtonotion.dependencies import get_client_ip, verify_api_key


class TestVerifyApiKey:
    """Test cases for verify_api_key dependency."""

    @pytest.mark.asyncio
    async def test_verify_api_key_valid(self):
        """Test authentication succeeds with valid API key."""
        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="127.0.0.1")

        settings = Settings()
        settings.api_key = "secret_key_123"

        result = await verify_api_key(
            request=mock_request,
            api_key="secret_key_123",
            settings=settings,
        )
        assert result == "secret_key_123"

    @pytest.mark.asyncio
    async def test_verify_api_key_missing_key(self):
        """Test authentication fails when API key is missing."""
        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="127.0.0.1")

        settings = Settings()
        settings.api_key = "secret_key_123"

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(
                request=mock_request,
                api_key=None,
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Missing API Key"

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid_key(self):
        """Test authentication fails with 401 when API key is invalid (and logs warning without NameError)."""
        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")

        settings = Settings()
        settings.api_key = "secret_key_123"

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(
                request=mock_request,
                api_key="wrong_key",
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Invalid API Key"

    @pytest.mark.asyncio
    async def test_verify_api_key_missing_server_config(self):
        """Test authentication fails with 500 when server API key is not configured."""
        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="127.0.0.1")

        settings = Settings()
        settings.api_key = ""

        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(
                request=mock_request,
                api_key="some_key",
                settings=settings,
            )
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Server API key configuration is missing" in exc_info.value.detail


class TestGetClientIp:
    """Test cases for get_client_ip helper."""

    def test_get_client_ip_with_client(self):
        """Test extracting IP when client is present."""
        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="10.0.0.1")
        assert get_client_ip(mock_request) == "10.0.0.1"

    def test_get_client_ip_without_client(self):
        """Test extracting IP when client is None."""
        mock_request = MagicMock(spec=Request)
        mock_request.client = None
        assert get_client_ip(mock_request) == "unknown"
