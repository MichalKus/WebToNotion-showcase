"""Main application entry point for WebToNotion.

This module initializes the FastAPI application, sets up logging,
configures middleware, and includes API routers.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from webtonotion.api.health import router as health_router
from webtonotion.api.middleware import (
    ContentLengthMiddleware,
    ErrorHandlingMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from webtonotion.api.process import router as process_router
from webtonotion.config.logging import setup_logging
from webtonotion.config.settings import settings
from webtonotion.dependencies import create_rate_limit_dependency, verify_api_key


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    # Startup
    logger = logging.getLogger(__name__)
    logger.info(
        f"Starting {settings.app_name} v{settings.app_version}",
        extra={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "debug": settings.debug,
            "environment": settings.environment,
        },
    )

    # Initialize services here if needed
    # await initialize_services()

    yield

    # Shutdown
    logger.info(f"Shutting down {settings.app_name}")
    # Cleanup services here if needed
    # await cleanup_services()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI-powered URL processing for Notion integration",
        debug=settings.debug,
        lifespan=lifespan,
    )
    setup_logging(app)

    # Add middleware (order matters - first added is outermost)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(ContentLengthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else settings.allowed_hosts,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Create rate limit dependency
    rate_limit_dep = create_rate_limit_dependency()

    app.include_router(
        process_router,
        prefix="/api/v1",
        dependencies=[Depends(verify_api_key), Depends(rate_limit_dep)],
    )
    app.include_router(health_router, prefix="/api/v1")

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "webtonotion.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.debug,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )
