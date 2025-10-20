"""Notion API integration service for WebToNotion application.

This module provides comprehensive integration with the Notion API, including
database management, page creation, and error handling with rate limiting.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from notion_client import Client
from notion_client.errors import (
    APIResponseError,
    HTTPResponseError,
    RequestTimeoutError,
)

from webtonotion.config.settings import Settings
from webtonotion.exceptions import (
    NotionAPIError,
    NotionAuthenticationError,
    NotionRateLimitError,
)
from webtonotion.models.notion import NotionDatabase, NotionPage, NotionPageResponse
from webtonotion.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class NotionService:
    """Service for interacting with the Notion API.

    This service provides methods for listing databases, creating pages,
    and handling authentication and rate limiting for the Notion API.
    """

    def __init__(self, settings: Settings, api_key: Optional[str] = None):
        """Initialize the Notion service.

        Args:
            settings: Application settings instance
            api_key: Notion API key. If not provided, uses settings.notion_api_key

        Raises:
            NotionAuthenticationError: If no API key is provided
        """
        self.settings = settings
        self.api_key = api_key or settings.notion_api_key
        logger.info(f"Initializing Notion service with API key: {self.api_key}")

        if not self.api_key:
            raise NotionAuthenticationError(
                "Notion API key is required. Set NOTION_API_KEY environment variable."
            )

        self.client = Client(
            auth=self.api_key,
            notion_version=settings.notion_version,
        )

        # Rate limiter: Notion allows 3 requests per second
        self.rate_limiter = RateLimiter(max_requests=3, time_window=1)

        logger.info("Notion service initialized successfully")

    async def _handle_api_error(self, error: Exception) -> None:
        """Handle and convert Notion API errors to service-specific exceptions.

        Args:
            error: The original exception from Notion API

        Raises:
            NotionAuthenticationError: For authentication-related errors
            NotionRateLimitError: For rate limit errors
            NotionAPIError: For other API errors
        """
        if isinstance(error, APIResponseError):
            error_message = error.args[0] if error.args else str(error)
            status_code = error.status if hasattr(error, "status") else 0

            if status_code == 401:
                raise NotionAuthenticationError(
                    f"Notion API authentication failed: {error_message}"
                ) from error
            elif status_code == 429:
                raise NotionRateLimitError(
                    f"Notion API rate limit exceeded: {error_message}"
                ) from error
            else:
                raise NotionAPIError(
                    f"Notion API error (status {status_code}): {error_message}"
                ) from error
        elif isinstance(error, RequestTimeoutError):
            raise NotionAPIError(f"Notion API request timeout: {str(error)}") from error
        elif isinstance(error, HTTPResponseError):
            raise NotionAPIError(f"Notion HTTP error: {str(error)}") from error
        else:
            raise NotionAPIError(f"Unexpected Notion API error: {str(error)}") from error

    async def get_databases(self) -> List[NotionDatabase]:
        """Retrieve all databases accessible to the integration.

        Returns:
            List of NotionDatabase objects

        Raises:
            NotionAuthenticationError: If authentication fails
            NotionRateLimitError: If rate limit is exceeded
            NotionAPIError: If API request fails
        """
        await self.rate_limiter.wait_if_needed()

        try:
            logger.info("Fetching Notion databases")
            response = self.client.search(filter={"property": "object", "value": "database"})

            databases = []
            for db_data in response.get("results", []):
                try:
                    # Extract database information
                    db_id = db_data["id"]

                    # Get database title
                    title_property = db_data.get("title", [])
                    name = ""
                    if title_property:
                        name = "".join([text.get("plain_text", "") for text in title_property])

                    # If no title, use a default name
                    if not name:
                        name = f"Database {db_id[:8]}"

                    database = NotionDatabase(
                        id=db_id,
                        name=name,
                        properties=db_data.get("properties", {}),
                        url=db_data.get("url"),
                        created_time=datetime.fromisoformat(
                            db_data["created_time"].replace("Z", "+00:00")
                        ),
                        last_edited_time=datetime.fromisoformat(
                            db_data["last_edited_time"].replace("Z", "+00:00")
                        ),
                    )
                    databases.append(database)

                except (KeyError, ValueError) as e:
                    logger.warning(f"Failed to parse database {db_data.get('id', 'unknown')}: {e}")
                    continue

            logger.info(f"Successfully retrieved {len(databases)} databases")
            return databases

        except Exception as e:
            logger.error(f"Failed to get databases: {e}")
            await self._handle_api_error(e)

    async def create_page(
        self,
        database_id: str,
        properties: Dict[str, Any],
        children: Optional[List[Dict[str, Any]]] = None,
    ) -> NotionPageResponse:
        """Create a new page in the specified database.

        Args:
            database_id: ID of the target database
            properties: Page properties matching the database schema
            children: Optional list of content blocks for the page

        Returns:
            NotionPageResponse with created page information

        Raises:
            NotionAuthenticationError: If authentication fails
            NotionRateLimitError: If rate limit is exceeded
            NotionAPIError: If API request fails
        """
        await self.rate_limiter.wait_if_needed()

        try:
            logger.info(f"Creating page in database {database_id}")

            # Prepare the page data
            page_data = {
                "parent": {"database_id": database_id},
                "properties": properties,
            }

            # Add children blocks if provided
            if children:
                page_data["children"] = children

            # Create the page
            response = self.client.pages.create(**page_data)

            # Create NotionPage object for the response
            notion_page = NotionPage(
                id=response["id"],
                database_id=database_id,
                properties=response.get("properties", {}),
                created_time=datetime.fromisoformat(
                    response["created_time"].replace("Z", "+00:00")
                ),
                last_edited_time=datetime.fromisoformat(
                    response["last_edited_time"].replace("Z", "+00:00")
                ),
                url=response["url"],
                archived=response.get("archived", False),
            )

            # Parse the response
            page_response = NotionPageResponse(
                id=response["id"],
                url=response["url"],
                created_time=datetime.fromisoformat(
                    response["created_time"].replace("Z", "+00:00")
                ),
                properties=response.get("properties", {}),
                page=notion_page,
                success=True,
                message="Page created successfully",
            )

            logger.info(f"Successfully created page {page_response.id}")
            return page_response

        except Exception as e:
            logger.error(f"Failed to create page in database {database_id}: {e}")
            await self._handle_api_error(e)

    async def get_database_properties(self, database_id: str) -> Dict[str, Any]:
        """Get the properties schema for a specific database.

        Args:
            database_id: ID of the database

        Returns:
            Dictionary containing the database properties schema

        Raises:
            NotionAuthenticationError: If authentication fails
            NotionRateLimitError: If rate limit is exceeded
            NotionAPIError: If API request fails
        """
        await self.rate_limiter.wait_if_needed()

        try:
            logger.info(f"Fetching properties for database {database_id}")
            response = self.client.databases.retrieve(database_id)

            properties = response.get("properties", {})
            logger.info(f"Retrieved {len(properties)} properties for database {database_id}")

            return properties

        except Exception as e:
            logger.error(f"Failed to get database properties for {database_id}: {e}")
            await self._handle_api_error(e)

    async def validate_database_access(self, database_id: str) -> bool:
        """Validate that the integration has access to a specific database.

        Args:
            database_id: ID of the database to validate

        Returns:
            True if database is accessible, False otherwise
        """
        try:
            await self.get_database_properties(database_id)
            return True
        except NotionAPIError:
            return False

    async def health_check(self) -> bool:
        """Check if the Notion API is accessible and responding.

        Returns:
            True if API is accessible, False otherwise
        """
        try:
            # Make a lightweight API call to check connectivity
            await self.rate_limiter.wait_if_needed()
            self.client.users.me()
            return True
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def format_page_properties(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Format content dictionary into Notion page properties.

        This method maps content fields to appropriate Notion property formats
        based on common naming conventions.

        Args:
            content: Dictionary of content to format

        Returns:
            Dictionary of formatted Notion properties
        """
        properties = {}

        # Map common field names to Notion property types
        property_mapping = {
            "title": "title",
            "name": "title",
            "url": "url",
            "link": "url",
            "description": "rich_text",
            "content": "rich_text",
            "summary": "rich_text",
            "author": "rich_text",
            "creator": "rich_text",
            "duration": "number",
            "length": "number",
            "count": "number",
            "tags": "multi_select",
            "categories": "multi_select",
            "topics": "multi_select",
            "email": "email",
            "phone": "phone_number",
            "published": "date",
            "published_date": "date",
            "date": "date",
            "completed": "checkbox",
            "done": "checkbox",
            "active": "checkbox",
        }

        # Format each content field according to mapping
        for key, value in content.items():
            # Convert key to title case for Notion property name
            property_name = key.replace("_", " ").title()

            # Determine property type based on mapping or default to rich_text
            property_type = property_mapping.get(key.lower(), "rich_text")

            # Format the property
            properties[property_name] = self.format_property_for_notion(property_type, value)

        return properties

    def format_property_for_notion(self, property_type: str, value: Any) -> Dict[str, Any]:
        """Format a value according to Notion property type requirements.

        Args:
            property_type: The Notion property type (title, rich_text, number, etc.)
            value: The value to format

        Returns:
            Formatted property value for Notion API
        """
        if property_type == "title":
            return {"title": [{"text": {"content": str(value)[:2000]}}]}  # Notion title limit
        elif property_type == "rich_text":
            return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}  # Notion text limit
        elif property_type == "number":
            try:
                return {"number": float(value)}
            except (ValueError, TypeError):
                return {"number": None}
        elif property_type == "select":
            return {"select": {"name": str(value)[:100]}}  # Select option limit
        elif property_type == "multi_select":
            if isinstance(value, (list, tuple)):
                return {
                    "multi_select": [
                        {"name": str(item)[:100]} for item in value[:10]  # Max 10 options
                    ]
                }
            else:
                return {"multi_select": [{"name": str(value)[:100]}]}
        elif property_type == "url":
            return {"url": str(value) if value else None}
        elif property_type == "email":
            return {"email": str(value) if value else None}
        elif property_type == "phone_number":
            return {"phone_number": str(value) if value else None}
        elif property_type == "date":
            if isinstance(value, datetime):
                return {"date": {"start": value.isoformat()}}
            elif isinstance(value, str):
                return {"date": {"start": value}}
            else:
                return {"date": None}
        elif property_type == "checkbox":
            return {"checkbox": bool(value)}
        else:
            # For unsupported types, try to convert to rich_text
            logger.warning(f"Unsupported property type '{property_type}', converting to rich_text")
            return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
