"""Health check and system status endpoints."""

import logging
import platform
import time
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from webtonotion.config.settings import settings

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
async def health_check() -> HealthResponse:
    """Basic health check endpoint.
    
    Returns:
        HealthResponse: Basic health status information
    """
    logger.debug("Health check requested")
    
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        version=settings.app_version,
        service=settings.app_name,
    )


@router.get("/status", response_model=SystemStatusResponse, status_code=status.HTTP_200_OK)
async def system_status() -> SystemStatusResponse:
    """Comprehensive system status endpoint.
    
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
        version=settings.app_version,
        service=settings.app_name,
        environment=settings.environment,
        debug=settings.debug,
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
    is_ready = all(
        check_status in ["ready", "not_configured"] 
        for check_status in checks.values()
    )
    
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