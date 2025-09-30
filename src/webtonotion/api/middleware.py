"""Middleware for FastAPI application.

This module contains custom middleware for error handling,
request logging, and other cross-cutting concerns.
"""

import logging
import time
import uuid
from typing import Callable

import logfire
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

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
            logger.info(
                f"Request started",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "url": str(request.url),
                    "client_ip": request.client.host if request.client else None,
                }
            )
            
            # Process request
            response = await call_next(request)
            
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Add headers to response
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = str(process_time)
            
            # Log successful response
            logger.info(
                f"Request completed",
                extra={
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "process_time": process_time,
                }
            )
            
            # Log to Logfire if available
            with logfire.span(
                "http_request",
                method=request.method,
                url=str(request.url),
                status_code=response.status_code,
                process_time=process_time,
            ):
                pass
            
            return response
            
        except HTTPException as e:
            # Handle FastAPI HTTP exceptions
            process_time = time.time() - start_time
            
            logger.warning(
                f"HTTP exception occurred",
                extra={
                    "request_id": request_id,
                    "status_code": e.status_code,
                    "detail": e.detail,
                    "process_time": process_time,
                }
            )
            
            response = JSONResponse(
                status_code=e.status_code,
                content={
                    "status": "error",
                    "message": e.detail,
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id, "X-Process-Time": str(process_time)},
            )
            
            return response
            
        except Exception as e:
            # Handle unexpected exceptions
            process_time = time.time() - start_time
            
            logger.error(
                f"Unhandled exception occurred",
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
                headers={"X-Request-ID": request_id, "X-Process-Time": str(process_time)},
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
            f"Request details",
            extra={
                "request_id": request_id,
                "headers": dict(request.headers),
                "query_params": dict(request.query_params),
                "path_params": request.path_params,
            }
        )
        
        response = await call_next(request)
        
        # Log response details (excluding body for performance)
        logger.debug(
            f"Response details",
            extra={
                "request_id": request_id,
                "response_headers": dict(response.headers),
                "status_code": response.status_code,
            }
        )
        
        return response