"""Main application entry point for WebToNotion.

This module initializes the FastAPI application, sets up logging,
configures middleware, and includes API routers.
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import logfire
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from webtonotion.config.settings import settings


def setup_logging() -> None:
    """Configure application logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Configure logfire if token is provided
    if settings.logfire_token:
        logfire.configure(
            token=settings.logfire_token,
            project_name=settings.logfire_project_name,
        )
        logfire.instrument_fastapi()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    # Startup
    logger = logging.getLogger(__name__)
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Log level: {settings.log_level}")

    # Initialize services here if needed
    # await initialize_services()

    yield

    # Shutdown
    logger.info(f"Shutting down {settings.app_name}")
    # Cleanup services here if needed
    # await cleanup_services()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI-powered URL processing for Notion integration",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # Add middleware
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

    # Include API routers
    # from webtonotion.api.process import router as process_router
    # app.include_router(process_router, prefix="/api/v1")

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "version": settings.app_version,
            "service": settings.app_name,
        }

    return app


def main() -> None:
    """Main entry point for running the application."""
    app = create_app()

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()