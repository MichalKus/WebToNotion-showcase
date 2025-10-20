"""Logging configuration for WebToNotion application.

This module provides structured logging configuration with support for
different environments, log levels, and output formats.
"""

import logging
import logging.config
import sys
from typing import Any, Dict

import logfire
from pythonjsonlogger import jsonlogger

from webtonotion.config.settings import settings


class StructuredFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter for structured logging."""

    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        """Add custom fields to log record."""
        super().add_fields(log_record, record, message_dict)

        # Add standard fields
        log_record["service"] = settings.app_name
        log_record["version"] = settings.app_version
        log_record["environment"] = settings.environment

        # Add request ID if available
        if hasattr(record, "request_id"):
            log_record["request_id"] = record.request_id

        # Add correlation ID if available
        if hasattr(record, "correlation_id"):
            log_record["correlation_id"] = record.correlation_id


def get_logging_config() -> Dict[str, Any]:
    """Get logging configuration based on environment settings."""

    # Determine log format based on environment
    if settings.environment == "development":
        formatter_class = "logging.Formatter"
        formatter_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    else:
        formatter_class = "webtonotion.config.logging.StructuredFormatter"
        formatter_format = "%(asctime)s %(name)s %(levelname)s %(message)s"

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "class": formatter_class,
                "format": formatter_format,
            },
            "json": {
                "class": "webtonotion.config.logging.StructuredFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": settings.log_level,
                "formatter": "standard",
                "stream": sys.stdout,
            },
        },
        "loggers": {
            "webtonotion": {
                "level": settings.log_level,
                "handlers": ["console"],
                "propagate": False,
            },
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
            },
        },
        "root": {
            "level": settings.log_level,
            "handlers": ["console"],
        },
    }

    return config


def setup_logging() -> None:
    """Configure application logging with structured format."""

    # Get logging configuration
    config = get_logging_config()

    # Apply logging configuration
    logging.config.dictConfig(config)

    # Configure logfire if token is provided
    if settings.logfire_token:
        try:
            logfire.configure(
                token=settings.logfire_token,
                project_name=settings.logfire_project_name,
                environment=settings.environment,
            )

            # Instrument FastAPI
            logfire.instrument_fastapi()

            # Log successful Logfire setup
            logger = logging.getLogger(__name__)
            logger.info("Logfire monitoring configured successfully")

        except Exception as e:
            # Log error but don't fail application startup
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to configure Logfire: {e}")

    # Log application startup
    logger = logging.getLogger(__name__)
    logger.info(
        "Logging configured",
        extra={
            "log_level": settings.log_level,
            "environment": settings.environment,
            "logfire_enabled": bool(settings.logfire_token),
        },
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name.

    Args:
        name: Logger name, typically __name__ of the calling module

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class LoggerMixin:
    """Mixin class to add logging capabilities to other classes."""

    @property
    def logger(self) -> logging.Logger:
        """Get logger instance for this class."""
        return get_logger(f"{self.__class__.__module__}.{self.__class__.__name__}")
