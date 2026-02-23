"""Middleware for FastAPI application.

This module contains custom middleware for error handling,
request logging, and other cross-cutting concerns.
"""

import logging
import time
import uuid
from typing import Callable

import logfire
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from webtonotion.config.settings import settings

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware for comprehensive error handling and logging."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and handle errors."""
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Add request ID to response headers
        start_time = time.time()

        try:
            # Log incoming request
            logger.debug(
                "Request started",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "url": str(request.url),
                    "client_ip": request.client.host if request.client else None,
                },
            )

            # Process request
            response = await call_next(request)

            # Calculate processing time
            process_time = time.time() - start_time

            # Add headers to response
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = str(process_time)

            # Log successful response
            logger.debug(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "process_time": process_time,
                },
            )

            return response

        except HTTPException as e:
            # Handle FastAPI HTTP exceptions
            process_time = time.time() - start_time

            logger.warning(
                "HTTP exception occurred",
                extra={
                    "request_id": request_id,
                    "status_code": e.status_code,
                    "detail": e.detail,
                    "process_time": process_time,
                },
            )

            response = JSONResponse(
                status_code=e.status_code,
                content={
                    "status": "error",
                    "message": e.detail,
                    "request_id": request_id,
                },
                headers={
                    "X-Request-ID": request_id,
                    "X-Process-Time": str(process_time),
                },
            )

            return response

        except Exception as e:
            # Handle unexpected exceptions
            process_time = time.time() - start_time

            logger.error(
                "Unhandled exception occurred",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "process_time": process_time,
                },
                exc_info=True,
            )

            # Log error to Logfire
            logfire.error(
                "Unhandled exception in request",
                request_id=request_id,
                error=str(e),
                error_type=type(e).__name__,
            )

            response = JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": "Internal server error occurred",
                    "request_id": request_id,
                },
                headers={
                    "X-Request-ID": request_id,
                    "X-Process-Time": str(process_time),
                },
            )

            return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for detailed request and response logging."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response details."""
        # Get request ID from previous middleware
        request_id = getattr(request.state, "request_id", "unknown")

        # Log request details
        logger.debug(
            "Request details",
            extra={
                "request_id": request_id,
                "headers": dict(request.headers),
                "query_params": dict(request.query_params),
                "path_params": request.path_params,
            },
        )

        response = await call_next(request)

        # Log response details (excluding body for performance)
        logger.debug(
            "Response details",
            extra={
                "request_id": request_id,
                "response_headers": dict(response.headers),
                "status_code": response.status_code,
            },
        )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to inject security headers into HTTP responses.

    This middleware adds standard security headers to protect against:
    - Cross-site scripting (XSS)
    - Clickjacking attacks
    - MIME-type sniffing
    - Man-in-the-middle attacks
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add security headers to response."""
        response = await call_next(request)

        # Content Security Policy (CSP)
        # Restricts sources for content loading to prevent XSS
        csp_policy = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.notion.com; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["Content-Security-Policy"] = csp_policy

        # X-Content-Type-Options
        # Prevents MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-Frame-Options
        # Prevents clickjacking by disallowing iframe embedding
        response.headers["X-Frame-Options"] = "DENY"

        # Strict-Transport-Security (HSTS)
        # Forces HTTPS connections for a specified duration
        if settings.environment == "production":
            # 1 year max-age, include subdomains, preload for HSTS preload list
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # X-XSS-Protection
        # Enables XSS filtering in browsers (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Additional security headers
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        logger.debug(
            "Security headers added to response",
            extra={
                "request_id": getattr(request.state, "request_id", "unknown"),
                "path": request.url.path,
                "method": request.method,
            },
        )

        return response
