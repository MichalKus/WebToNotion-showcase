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
        notion_api_key: Notion API integration token for database operations
        logfire_token: Logfire authentication token for monitoring and logging
        api_key: Optional API key for securing the application endpoints
        rate_limit_requests: Maximum number of requests per minute per IP
        rate_limit_window: Time window for rate limiting in seconds
        cors_origins: List of allowed CORS origins
        debug: Enable debug mode for development
        environment: Application environment (development, staging, production)
        max_content_length: Maximum content length for video processing
        request_timeout: Request timeout in seconds
        cache_ttl: Cache time-to-live in seconds
        background_task_timeout: Background task timeout in seconds
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core API Configuration
    notion_api_key: str = Field(
        ..., description="Notion API integration token", min_length=1
    )
    
    logfire_token: str = Field(
        ..., description="Logfire authentication token", min_length=1
    )
    
    api_key: str | None = Field(
        default=None, description="API key for securing the API"
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
        default_factory=lambda: ["*"], 
        description="Allowed CORS origins"
    )

    # Application Configuration
    debug: bool = Field(
        default=False, description="Enable debug mode"
    )
    
    environment: str = Field(
        default="development", 
        description="Application environment (development, staging, production)"
    )

    # Processing Configuration
    max_content_length: int = Field(
        default=100 * 1024 * 1024,  # 100MB
        description="Maximum content length for video processing in bytes",
        ge=1024
    )
    
    request_timeout: int = Field(
        default=300, description="Request timeout in seconds", ge=1
    )
    
    background_task_timeout: int = Field(
        default=600, description="Background task timeout in seconds", ge=1
    )

    # Caching Configuration
    cache_ttl: int = Field(
        default=3600, description="Cache time-to-live in seconds", ge=0
    )

    # Server Configuration
    host: str = Field(
        default="0.0.0.0", description="Server host address"
    )
    
    port: int = Field(
        default=8000, description="Server port", ge=1, le=65535
    )
    
    workers: int = Field(
        default=1, description="Number of worker processes", ge=1
    )


# Global instance of the settings
settings = Settings()