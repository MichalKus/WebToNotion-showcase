"""Services package for WebToNotion application.

This package contains service classes that provide specific functionalities
for the application, including Notion API integration, video scraping,
and monitoring services.
"""

from .notion_service import NotionService

__all__ = ["NotionService"]
