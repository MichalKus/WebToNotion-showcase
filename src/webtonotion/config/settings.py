"""Application settings and configuration management.

This module provides centralized configuration management using Pydantic Settings
for environment variables and application configuration.
"""

from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Settings
    app_name: str = Field(default="WebToNotion", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")

    # Notion API Configuration
    notion_api_key: str = Field(
        ..., description="Notion API integration token", min_length=1
    )
    notion_version: str = Field(
        default="2022-06-28", description="Notion API version"
    )

    # Logfire Configuration
    logfire_token: Optional[str] = Field(
        default=None, description="Logfire authentication token"
    )
    logfire_project_name: str = Field(
        default="webtonotion", description="Logfire project name"
    )

    # Web Scraping Configuration
    user_agent: str = Field(
        default="WebToNotion/0.1.0 (https://github.com/MichalKus/WebToNotion)",
        description="User agent for web requests",
    )
    request_timeout: int = Field(
        default=30, description="HTTP request timeout in seconds", ge=1, le=300
    )
    max_retries: int = Field(
        default=3, description="Maximum number of request retries", ge=0, le=10
    )

    # Playwright Configuration
    playwright_headless: bool = Field(
        default=True, description="Run Playwright in headless mode"
    )
    playwright_timeout: int = Field(
        default=30000, description="Playwright timeout in milliseconds", ge=1000
    )

    # Rate Limiting
    rate_limit_requests: int = Field(
        default=100, description="Number of requests per window", ge=1
    )
    rate_limit_window: int = Field(
        default=3600, description="Rate limit window in seconds", ge=1
    )

    # Security
    secret_key: str = Field(
        ..., description="Secret key for security operations", min_length=32
    )
    allowed_hosts: List[str] = Field(
        default=["localhost", "127.0.0.1"], description="Allowed hosts"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the standard levels."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {', '.join(valid_levels)}")
        return v.upper()

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v) -> List[str]:
        """Parse allowed hosts from comma-separated string or list."""
        if isinstance(v, str):
            return [host.strip() for host in v.split(",") if host.strip()]
        return v

    @property
    def is_development(self) -> bool:
        """Check if application is running in development mode."""
        return self.debug

    @property
    def is_production(self) -> bool:
        """Check if application is running in production mode."""
        return not self.debug

    def get_database_url(self) -> str:
        """Get database URL (placeholder for future database integration)."""
        # This is a placeholder for future database configuration
        return "sqlite:///./webtonotion.db"

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()