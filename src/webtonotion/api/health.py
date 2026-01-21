"""Health check and system status endpoints."""

import logging
import platform
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from webtonotion.config.settings import Settings
from webtonotion.dependencies import get_notion_service, get_settings, verify_api_key
from webtonotion.exceptions import NotionAPIError, NotionAuthenticationError
from webtonotion.services.notion_service import NotionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    timestamp: datetime
    version: str
    service: str


class SystemStatusResponse(BaseModel):
    """System status response model."""

    status: str
    timestamp: datetime
    version: str
    service: str
    environment: str
    debug: bool
    system_info: Dict[str, Any]
    uptime_seconds: float


# Track application start time
_start_time = time.time()


@router.get("/", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Basic health check endpoint.

    Args:
        app_settings: Application settings injected via dependency injection

    Returns:
        HealthResponse: Basic health status information
    """
    logger.debug("Health check requested")

    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        version=app_settings.app_version,
        service=app_settings.app_name,
    )


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def system_status(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> SystemStatusResponse:
    """Comprehensive system status endpoint.

    Args:
        app_settings: Application settings injected via dependency injection

    Returns:
        SystemStatusResponse: Detailed system status information
    """
    logger.debug("System status requested")

    current_time = time.time()
    uptime = current_time - _start_time

    system_info = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
    }

    return SystemStatusResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        version=app_settings.app_version,
        service=app_settings.app_name,
        environment=app_settings.environment,
        debug=app_settings.debug,
        system_info=system_info,
        uptime_seconds=round(uptime, 2),
    )


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check() -> Dict[str, Any]:
    """Readiness check endpoint for container orchestration.

    Returns:
        Dict[str, Any]: Readiness status
    """
    logger.debug("Readiness check requested")

    # Add checks for external dependencies here
    # For now, we'll just return ready status
    checks = {
        "database": "not_configured",  # Will be updated when database is added
        "notion_api": "not_configured",  # Will be updated when Notion integration is added
        "external_services": "ready",
    }

    # Determine overall readiness
    is_ready = all(check_status in ["ready", "not_configured"] for check_status in checks.values())

    return {
        "status": "ready" if is_ready else "not_ready",
        "timestamp": datetime.now(timezone.utc),
        "checks": checks,
    }


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check() -> Dict[str, str]:
    """Liveness check endpoint for container orchestration.

    Returns:
        Dict[str, str]: Liveness status
    """
    logger.debug("Liveness check requested")

    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/notion-health", status_code=status.HTTP_200_OK)
async def notion_health_check(
    notion_service: Annotated[
        NotionService,
        Depends(get_notion_service),
    ],
) -> Dict[str, Any]:
    """Check the health of the Notion API connection.

    Args:
        notion_service: NotionService instance injected via dependency injection

    Returns:
        Dict[str, Any]: Notion API health status
    """
    logger.debug("Notion health check requested")
    try:
        if await notion_service.health_check():
            return {"status": "ok", "message": "Notion API is healthy"}
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Notion API health check failed",
            )
    except NotionAuthenticationError as e:
        logger.error(f"Notion authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Notion API authentication failed: {e.message}",
        )
    except NotionAPIError as e:
        logger.error(f"Notion API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Notion API error: {e.message}",
        )
