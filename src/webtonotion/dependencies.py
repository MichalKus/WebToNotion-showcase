from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from webtonotion.config.settings import Settings
from webtonotion.utils.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from webtonotion.agents.chat_service import ChatService
    from webtonotion.agents.deps import AgentDeps
    from webtonotion.agents.session.store import SessionStore
    from webtonotion.services.notion_service import NotionService
    from webtonotion.services.video_scraping_service import VideoScrapingService

logger = logging.getLogger(__name__)

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
) -> NotionService:
    """Get NotionService instance with injected settings.

    Args:
        app_settings: Application settings injected by FastAPI

    Returns:
        NotionService: Configured NotionService instance
    """
    # Import here to avoid circular imports
    from webtonotion.services.notion_service import NotionService

    return NotionService(settings=app_settings)


def get_video_scraping_service() -> VideoScrapingService:
    """Get VideoScrapingService instance.

    Returns:
        VideoScrapingService: Configured VideoScrapingService instance
    """
    # Import here to avoid circular imports
    from webtonotion.services.video_scraping_service import VideoScrapingService

    return VideoScrapingService()


@lru_cache
def get_session_store() -> "SessionStore":
    """Get the process-wide session store singleton.

    Built lazily on first use (never at import time, so a missing OpenRouter key
    cannot break import) and reused across requests. Call ``init_schema`` once at
    startup before serving.

    The db path is passed explicitly from ``get_settings()`` rather than left to
    ``SqliteStore``'s own default, so a settings override (e.g. in tests) actually
    reaches the store instead of it silently reading the module-level singleton.

    Returns:
        SessionStore: The SQLite-backed session store.
    """
    from webtonotion.agents.session.sqlite_store import SqliteStore

    return SqliteStore(db_path=get_settings().session_db_path)


@lru_cache
def get_orchestrator() -> "Agent[AgentDeps, str]":
    """Get the process-wide orchestrator agent singleton.

    The agent is built once (per pydantic-ai conventions: instantiate an agent
    once and reuse it, never per request) and lazily (not at import time). The
    OpenRouter model is constructed here rather than at module import so the app
    imports without an API key.

    Returns:
        Agent[AgentDeps, str]: The configured orchestrator agent.
    """
    from webtonotion.agents.orchestrator import build_orchestrator

    return build_orchestrator(get_settings())


def get_chat_service(
    app_settings: Annotated[Settings, Depends(get_settings)],
    notion_service: Annotated[Any, Depends(get_notion_service)],
) -> "ChatService":
    """Get a ChatService wired with the singleton store and orchestrator.

    The store and agent are process-wide singletons; only the thin service wrapper
    (and its per-request NotionService) is constructed here.

    Args:
        app_settings: Application settings injected by FastAPI.
        notion_service: Per-request Notion API client. Typed ``Any`` here (not
            ``NotionService``) because that type only exists under
            ``TYPE_CHECKING`` in this module — with ``from __future__ import
            annotations`` active, FastAPI resolves every parameter annotation
            when it walks the dependency tree to build ``/openapi.json``, and a
            genuinely undefined name breaks that walk even though the request
            path itself never needed it.

    Returns:
        ChatService: Ready to handle one chat turn.
    """
    from webtonotion.agents.chat_service import ChatService

    return ChatService(
        agent=get_orchestrator(),
        store=get_session_store(),
        notion_service=notion_service,
        settings=app_settings,
    )


async def verify_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """Verify API key for request authentication.

    Args:
        request: FastAPI request object
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
        client_ip = get_client_ip(request)
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
