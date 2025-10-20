"""Dependency injection providers for the WebToNotion application.

This module centralizes the creation and management of application dependencies
using FastAPI's dependency injection system for better testability and maintainability.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from webtonotion.config.settings import Settings


@lru_cache
def get_settings() -> Settings:
    """Get application settings instance.
    
    Uses lru_cache to ensure settings are loaded only once and reused
    across all requests for better performance.
    
    Returns:
        Settings: Application settings instance
    """
    return Settings()


def get_notion_service(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> "NotionService":
    """Get NotionService instance with injected settings.
    
    Args:
        app_settings: Application settings injected by FastAPI
        
    Returns:
        NotionService: Configured NotionService instance
    """
    # Import here to avoid circular imports
    from webtonotion.services.notion_service import NotionService
    
    return NotionService(settings=app_settings)