"""Application settings and configuration management.

This module provides centralized configuration management using Pydantic Settings
for environment variables and application configuration.
"""

from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def parse_comma_separated_list(v: Any) -> list[str]:
    """Parse comma-separated string into a list of strings."""
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return v


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    This class manages all configuration settings for the WebToNotion application,
    loading values from environment variables and .env files.

    Attributes:
        # Application Metadata
        app_name: Application name for identification
        app_version: Application version for tracking

        # Core API Configuration
        notion_api_key: Notion API integration token for database operations
        notion_version: Notion API version to use
        logfire_token: Logfire authentication token for monitoring and logging
        logfire_project_name: Logfire project name for identification
        api_key: Optional API key for securing the application endpoints
        max_retries: Maximum number of retry attempts for network operations

        # Logging Configuration
        log_level: Logging level for the application

        # Rate Limiting Configuration
        rate_limit_requests: Maximum number of requests per minute per IP
        rate_limit_window: Time window for rate limiting in seconds

        # Application Configuration
        debug: Enable debug mode for development
        environment: Application environment (development, staging, production)

        # Security Configuration
        allowed_hosts: List of allowed host names for security

        # Processing Configuration
        max_content_length: Maximum content length for processing in bytes
        request_timeout: Request timeout in seconds

        # Server Configuration
        host: Server host address
        port: Server port number
        workers: Number of worker processes for handling requests
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Metadata
    app_name: str = Field(default="WebToNotion", description="Application name for identification")

    app_version: str = Field(default="0.1.0", description="Application version for tracking")

    # Core API Configuration
    notion_api_key: str | None = Field(default=None, description="Notion API integration token")

    notion_version: str = Field(default="2025-09-03", description="Notion API version to use")

    logfire_token: str | None = Field(default=None, description="Logfire authentication token")

    logfire_project_name: str = Field(
        default="webtonotion", description="Logfire project name for identification"
    )

    api_key: str | None = Field(default=None, description="API key for securing the API")

    max_retries: int = Field(
        default=3, description="Maximum retry attempts for network operations", ge=0
    )

    # Agentic Orchestrator Configuration
    agent_max_requests: int = Field(
        default=15,
        description="Maximum model requests per orchestrator run (runaway-loop bound)",
        ge=1,
    )

    agent_thinking_level: Literal["off", "minimal", "low", "medium", "high", "xhigh"] = Field(
        default="medium",
        description=(
            "Reasoning effort for the orchestrator agent. 'off' disables thinking; "
            "higher levels cost more reasoning tokens. Requires a reasoning-capable model."
        ),
    )

    session_db_path: str = Field(
        default="./cache/sessions.db",
        description="SQLite path for chat session and message-history storage",
    )

    # Logging Configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Rate Limiting Configuration
    rate_limit_requests: int = Field(
        default=100, description="Maximum requests per minute per IP", ge=1
    )

    rate_limit_window: int = Field(
        default=3600, description="Rate limit time window in seconds", ge=1
    )

    # Application Configuration
    debug: bool = Field(default=False, description="Enable debug mode")

    environment: str = Field(
        default="development",
        description="Application environment (development, staging, production)",
    )

    # Security Configuration
    allowed_hosts: Annotated[list[str], NoDecode, BeforeValidator(parse_comma_separated_list)] = (
        Field(
            default_factory=lambda: ["localhost", "127.0.0.1"],
            description="List of allowed host names (comma-separated)",
        )
    )

    # Processing Configuration
    max_content_length: int = Field(
        default=100 * 1024 * 1024,  # 100MB
        description="Maximum content length for processing in bytes",
        ge=1024,
    )

    request_timeout: int = Field(default=300, description="Request timeout in seconds", ge=1)

    # Video Processing Configuration
    cache_dir: str = Field(default="./cache", description="Directory for caching processed content")

    max_video_duration: int = Field(
        default=3600, description="Maximum video duration in seconds (1 hour)", ge=1
    )

    enable_caching: bool = Field(default=True, description="Enable/disable caching")

    # OpenRouter Configuration
    openrouter_api_key: str | None = Field(
        default=None, description="OpenRouter API key for AI analysis"
    )

    openrouter_model: str = Field(
        default="openai/gpt-4o-mini",
        description="OpenRouter model for AI analysis (e.g., anthropic/claude-3.5-sonnet, openai/gpt-4o-mini)",
    )

    whisper_api_key: str | None = Field(
        default=None, description="Whisper API key for Groq service"
    )

    whisper_model: str = Field(
        default="whisper-large-v3",
        description="Whisper model size (tiny, base, small, medium, large)",
    )

    audio_quality: str = Field(
        default="best", description="Audio quality for transcription (best, good, medium)"
    )

    cache_expiration: int = Field(
        default=86400, description="Cache expiration in seconds (0 = never expire)", ge=0
    )

    temp_dir: str = Field(
        default="/tmp/webtonotion", description="Temporary directory for processing"
    )

    cleanup_temp_files: bool = Field(
        default=True, description="Clean up temporary files after processing"
    )

    max_file_size: int = Field(
        default=500 * 1024 * 1024,  # 500MB
        description="Maximum file size for download in bytes",
        ge=1024 * 1024,
    )

    verbose_logging: bool = Field(
        default=False, description="Enable verbose logging for video processing"
    )

    cookies_file_path: str | None = Field(
        default=None, description="Path to cookies.txt file for yt-dlp authentication"
    )

    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host address")

    port: int = Field(default=8000, description="Server port", ge=1, le=65535)

    workers: int = Field(
        default=1,
        description="Number of worker processes for handling requests",
        ge=1,
        le=32,
    )

    forwarded_allow_ips: str = Field(
        default="*", description="Comma separated list of IPs to trust as proxies"
    )

    @field_validator("max_file_size", mode="before")
    @classmethod
    def parse_max_file_size(cls, v: Any) -> int:
        """Parse file size string (e.g., '100MB') into bytes."""
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            size_str = v.strip().upper()
            if size_str.endswith("KB"):
                return int(float(size_str.replace("KB", "")) * 1024)
            if size_str.endswith("MB"):
                return int(float(size_str.replace("MB", "")) * 1024 * 1024)
            if size_str.endswith("GB"):
                return int(float(size_str.replace("GB", "")) * 1024 * 1024 * 1024)
            try:
                return int(size_str)
            except ValueError:
                pass
        raise ValueError(
            f"Invalid max_file_size format: {v}. Expected an integer or a string like '500MB', '1GB', etc."
        )


# Global instance of the settings
settings = Settings()
