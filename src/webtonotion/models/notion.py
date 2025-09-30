"""Notion API data models.

This module defines Pydantic models for interacting with the Notion API,
including database and page representations.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotionDatabase(BaseModel):
    """Represents a Notion database with its properties.
    
    This model encapsulates the structure and metadata of a Notion database,
    providing a standardized interface for database operations.
    
    Attributes:
        id: Unique identifier for the database
        title: Human-readable name of the database
        properties: Database schema defining available properties and their types
        created_time: Timestamp when the database was created
        last_edited_time: Timestamp of the last modification
        url: Direct URL to access the database in Notion
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "12345678-1234-1234-1234-123456789012",
                "title": "Video Content Database",
                "properties": {
                    "Title": {"type": "title"},
                    "URL": {"type": "url"},
                    "Author": {"type": "rich_text"},
                    "Topics": {"type": "multi_select"}
                },
                "created_time": "2024-01-01T00:00:00.000Z",
                "last_edited_time": "2024-01-01T12:00:00.000Z",
                "url": "https://notion.so/database/12345678123412341234123456789012"
            }
        }
    )

    id: str = Field(..., description="Unique database identifier")
    title: str = Field(..., description="Database title", min_length=1)
    properties: dict[str, dict[str, str]] = Field(
        default_factory=dict, 
        description="Database schema properties"
    )
    created_time: datetime | None = Field(default=None, description="Creation timestamp")
    last_edited_time: datetime | None = Field(default=None, description="Last edit timestamp")
    url: str | None = Field(default=None, description="Direct URL to the database")


class NotionPage(BaseModel):
    """Represents a Notion page with its content and properties.
    
    This model defines the structure for creating and managing pages within
    Notion databases, including all necessary metadata and content.
    
    Attributes:
        id: Unique identifier for the page (optional for creation)
        database_id: ID of the parent database
        properties: Page properties matching the database schema
        created_time: Timestamp when the page was created
        last_edited_time: Timestamp of the last modification
        url: Direct URL to access the page in Notion
        archived: Whether the page is archived
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "87654321-4321-4321-4321-210987654321",
                "database_id": "12345678-1234-1234-1234-123456789012",
                "properties": {
                    "Title": {
                        "title": [{"text": {"content": "Never Gonna Give You Up"}}]
                    },
                    "URL": {
                        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                    },
                    "Author": {
                        "rich_text": [{"text": {"content": "Rick Astley"}}]
                    }
                },
                "created_time": "2024-01-01T00:00:00.000Z",
                "last_edited_time": "2024-01-01T12:00:00.000Z",
                "url": "https://notion.so/page/87654321432143214321210987654321",
                "archived": False
            }
        }
    )

    id: str | None = Field(default=None, description="Unique page identifier")
    database_id: str = Field(..., description="Parent database ID")
    properties: dict[str, dict] = Field(
        default_factory=dict, 
        description="Page properties matching database schema"
    )
    created_time: datetime | None = Field(default=None, description="Creation timestamp")
    last_edited_time: datetime | None = Field(default=None, description="Last edit timestamp")
    url: str | None = Field(default=None, description="Direct URL to the page")
    archived: bool = Field(default=False, description="Whether the page is archived")