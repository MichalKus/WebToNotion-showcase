"""Dependency injection providers for the WebToNotion application.

This module centralizes the creation and management of application dependencies
using FastAPI's dependency injection system for better testability and maintainability.
"""

import secrets
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from webtonotion.config.settings import Settings
from webtonotion.utils.rate_limiter import RateLimiter

# API Key header configuration
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Rate limiter instances per IP storage
rate_limiters: dict[str, RateLimiter] = {}


@lru_cache
def get_settings() -> Settings:
    """Get application settings instance.

    Uses lru_cache to ensure settings are loaded only once and reused
    across all requests for better performance.

    Returns:
        Settings: Application settings instance
    """
    return Settings()


def get_notion_service(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> "NotionService":
    """Get NotionService instance with injected settings.

    Args:
        app_settings: Application settings injected by FastAPI

    Returns:
        NotionService: Configured NotionService instance
    """
    # Import here to avoid circular imports
    from webtonotion.services.notion_service import NotionService

    return NotionService(settings=app_settings)


def get_video_scraping_service() -> "VideoScrapingService":
    """Get VideoScrapingService instance.

    Returns:
        VideoScrapingService: Configured VideoScrapingService instance
    """
    # Import here to avoid circular imports
    from webtonotion.services.video_scraping_service import VideoScrapingService

    return VideoScrapingService()


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Verify API key for request authentication.

    Args:
        api_key: API key from request header
        settings: Application settings

    Returns:
        str: Validated API key

    Raises:
        HTTPException: If API key is invalid or missing
    """
    if not settings.api_key:
        # If no API key is configured in settings, we should fail secure
        # effectively disabling the API until configured
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server API key configuration is missing",
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key",
        )

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, settings.api_key):
        # Log failed authentication attempt with client IP
        client_ip = get_client_ip(request) if "request" in locals() else "unknown"
        logger.warning(f"Auth failed for IP {client_ip}: Invalid API Key")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    return api_key


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request.

    Args:
        request: FastAPI request object

    Returns:
        str: Client IP address
    """
    return request.client.host if request.client else "unknown"


def create_rate_limit_dependency():
    """Create a rate limiting dependency function.

    Returns:
        Dependency function for rate limiting
    """

    async def rate_limit_dependency(
        request: Request,
        settings: Settings = Depends(get_settings),
    ) -> None:
        """Rate limiting dependency to prevent DoS attacks.

        Args:
            request: FastAPI request object (injected automatically)
            settings: Application settings

        Raises:
            HTTPException: If rate limit is exceeded
        """
        # Get client IP address
        client_ip = get_client_ip(request)

        # Get or create rate limiter for this IP
        if client_ip not in rate_limiters:
            rate_limiters[client_ip] = RateLimiter(
                max_requests=settings.rate_limit_requests,
                time_window=settings.rate_limit_window,
            )

        rate_limiter = rate_limiters[client_ip]

        # Check if we need to wait (this will block if rate limit is exceeded)
        await rate_limiter.wait_if_needed()

    return rate_limit_dependency
