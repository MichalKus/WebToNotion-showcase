"""Application settings and configuration management.

This module provides centralized configuration management using Pydantic Settings
for environment variables and application configuration.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

        # Logging Configuration
        log_level: Logging level for the application

        # Rate Limiting Configuration
        rate_limit_requests: Maximum number of requests per minute per IP
        rate_limit_window: Time window for rate limiting in seconds

        # CORS Configuration
        cors_origins: List of allowed CORS origins

        # Application Configuration
        debug: Enable debug mode for development
        environment: Application environment (development, staging, production)

        # Web Scraping Configuration
        user_agent: User agent string for web requests
        max_retries: Maximum number of retry attempts for failed requests

        # Playwright Configuration
        playwright_headless: Run Playwright browser in headless mode
        playwright_timeout: Playwright operation timeout in milliseconds

        # Security Configuration
        secret_key: Secret key for cryptographic operations
        allowed_hosts: List of allowed host names for security

        # Processing Configuration
        max_content_length: Maximum content length for video processing
        request_timeout: Request timeout in seconds
        cache_ttl: Cache time-to-live in seconds
        background_task_timeout: Background task timeout in seconds

        # Server Configuration
        host: Server host address
        port: Server port number
        workers: Number of worker processes
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

    notion_version: str = Field(default="2022-06-28", description="Notion API version to use")

    logfire_token: str | None = Field(default=None, description="Logfire authentication token")

    logfire_project_name: str = Field(
        default="webtonotion", description="Logfire project name for identification"
    )

    api_key: str | None = Field(default=None, description="API key for securing the API")

    # Logging Configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Rate Limiting Configuration
    rate_limit_requests: int = Field(
        default=60, description="Maximum requests per minute per IP", ge=1
    )

    rate_limit_window: int = Field(
        default=60, description="Rate limit time window in seconds", ge=1
    )

    # CORS Configuration
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed CORS origins"
    )

    # Application Configuration
    debug: bool = Field(default=False, description="Enable debug mode")

    environment: str = Field(
        default="development",
        description="Application environment (development, staging, production)",
    )

    # Web Scraping Configuration
    user_agent: str = Field(
        default="WebToNotion/0.1.0 (https://github.com/MichalKus/WebToNotion)",
        description="User agent string for web requests",
    )

    max_retries: int = Field(
        default=3, description="Maximum retry attempts for failed requests", ge=0
    )

    # Playwright Configuration
    playwright_headless: bool = Field(
        default=True, description="Run Playwright browser in headless mode"
    )

    playwright_timeout: int = Field(
        default=30000,
        description="Playwright operation timeout in milliseconds",
        ge=1000,
    )

    # Security Configuration
    secret_key: str = Field(
        default="dev-secret-key-change-in-production-32chars",
        description="Secret key for cryptographic operations",
        min_length=32,
    )

    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"],
        description="List of allowed host names for security",
    )

    # Processing Configuration
    max_content_length: int = Field(
        default=100 * 1024 * 1024,  # 100MB
        description="Maximum content length for video processing in bytes",
        ge=1024,
    )

    request_timeout: int = Field(default=300, description="Request timeout in seconds", ge=1)

    background_task_timeout: int = Field(
        default=600, description="Background task timeout in seconds", ge=1
    )

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

    max_concurrent_downloads: int = Field(
        default=3, description="Maximum concurrent video downloads", ge=1
    )

    audio_quality: str = Field(
        default="best", description="Audio quality for transcription (best, good, medium)"
    )

    chunk_size: int = Field(default=1024, description="Audio processing chunk size", ge=1)

    cache_expiration: int = Field(
        default=86400, description="Cache expiration in seconds (0 = never expire)", ge=0
    )

    max_file_size: str = Field(
        default="100MB", description="Maximum file size for video downloads (e.g., '100MB')"
    )

    temp_dir: str = Field(
        default="/tmp/webtonotion", description="Temporary directory for processing"
    )

    cleanup_temp_files: bool = Field(
        default=True, description="Clean up temporary files after processing"
    )

    max_file_size: str = Field(default="500MB", description="Maximum file size for download")

    max_concurrent_jobs: int = Field(
        default=5, description="Maximum concurrent processing jobs", ge=1
    )

    verbose_logging: bool = Field(
        default=False, description="Enable verbose logging for video processing"
    )

    # Caching Configuration
    cache_ttl: int = Field(default=3600, description="Cache time-to-live in seconds", ge=0)

    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host address")

    port: int = Field(default=8000, description="Server port", ge=1, le=65535)

    workers: int = Field(default=1, description="Number of worker processes", ge=1)


# Global instance of the settings
settings = Settings()
