"""Notion API integration service for WebToNotion application.

This module provides comprehensive integration with the Notion API, including
database management, page creation, and error handling with rate limiting.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, NoReturn, Optional

from notion_client import Client
from notion_client.errors import APIResponseError, HTTPResponseError, RequestTimeoutError

from webtonotion.config.settings import Settings
from webtonotion.exceptions import NotionAPIError, NotionAuthenticationError, NotionRateLimitError
from webtonotion.models.notion import NotionDatabase, NotionPage, NotionPageResponse
from webtonotion.models.video import VideoContent
from webtonotion.services.analysis.notion_mapper import MapperDependencies, notion_mapper_agent
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

        if not self.api_key:
            raise NotionAuthenticationError(
                "Notion API key is required. Set NOTION_API_KEY environment variable."
            )

        self.client = Client(
            auth=self.api_key,
            notion_version=settings.notion_version,
            timeout_ms=settings.request_timeout * 1000,
        )

        # Rate limiter: Notion allows 3 requests per second
        self.rate_limiter = RateLimiter(max_requests=3, time_window=1)

    async def _handle_api_error(self, error: Exception) -> NoReturn:
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

    async def create_video_page(
        self,
        database_id: str,
        video_content: VideoContent,
        db_schema: Optional[Dict[str, Any]] = None,
    ) -> NotionPageResponse:
        """Create a new page with video content in the specified database."""
        try:
            if db_schema is None:
                db_schema = await self.get_database_properties(database_id)

            logger.info(f"Schema properties: {list(db_schema.keys())}")

            deps = MapperDependencies(schema=db_schema, database_id=database_id)

            logger.info(f"Invoking NotionMapperAgent for database {database_id}")

            # Create a descriptive prompt for the agent based on video content
            prompt = f"""Map this video content to the Notion database schema:
                Video Title: {video_content.title}
                Video Author: {video_content.author}
                Video URL: {video_content.url}
                Video Description: {video_content.description}
                Video Duration: {video_content.duration} seconds
                Published At: {video_content.published_at}
                Transcript: {video_content.transcript[:500]}...  # First 500 chars of transcript
                Topics: {', '.join(video_content.topics)}
                Sentiment: {video_content.sentiment}
                Locations: {', '.join(video_content.locations) if video_content.locations else 'None'}
                Metadata: {video_content.metadata}

            Please analyze this video content and create a Notion page payload that maps all relevant information to the provided database schema."""

            result = await notion_mapper_agent.run(prompt, deps=deps)
            page_payload = result.output
            logger.debug(f"Agent payload: {page_payload}")

            # Extract properties and children from the payload
            # Filter out empty property values (e.g. properties that serialized to {})
            # This is crucial because Pydantic's exclude_none=True can leave empty dicts
            # for optional fields like 'select', 'date', etc., which Notion rejects.
            properties = {
                k: v for k, v in page_payload.properties.items() if v  # Keep only non-empty values
            }

            logger.info(f"Successfully parsed page data for notion page creation")
            return await self.create_page(
                database_id=database_id,
                properties=properties,
                children=page_payload.children,
            )

        except Exception as e:
            logger.error(f"Failed to create video page via AI Agent: {e}")
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
            # First get database details
            logger.info(f"Fetching properties for database {database_id}")
            database_details = self.client.databases.retrieve(
                database_id,
            )
            logger.debug(f"Database details: {database_details}")

            # Retrieve data source from database details
            data_sources = database_details.get("data_sources", [])
            data_source_id = data_sources[0]["id"]
            logger.debug(f"Data source ID: {data_source_id}")

            # Now get properties from the data source
            ds_info = self.client.data_sources.retrieve(data_source_id=data_source_id)
            properties = ds_info["properties"]
            logger.info(f"Found {len(properties)} properties in data source")

            return properties
        except Exception as e:
            logger.error(f"Failed to get database properties for {database_id}: {e}")
            await self._handle_api_error(e)

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
