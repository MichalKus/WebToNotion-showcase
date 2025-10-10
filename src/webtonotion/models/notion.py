"""Notion API data models.

This module defines Pydantic models for interacting with the Notion API,
including database and page representations.
"""

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class NotionDatabase(BaseModel):
    """Represents a Notion database with its properties.
    
    This model encapsulates the structure and metadata of a Notion database,
    providing a standardized interface for database operations.
    
    Attributes:
        id: Unique identifier for the database
        name: Human-readable name of the database (changed from title for consistency)
        properties: Database schema defining available properties and their types
        created_time: Timestamp when the database was created
        last_edited_time: Timestamp of the last modification
        url: Direct URL to access the database in Notion
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "12345678-1234-1234-1234-123456789012",
                "name": "Video Content Database",
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
    name: str = Field(..., description="Database name", min_length=1)
    properties: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Database schema properties"
    )
    created_time: datetime = Field(..., description="Creation timestamp")
    last_edited_time: datetime = Field(..., description="Last edit timestamp")
    url: str = Field(..., description="Direct URL to the database")


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

    id: str = Field(..., description="Unique page identifier")
    database_id: str = Field(..., description="Parent database ID")
    properties: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Page properties matching database schema"
    )
    created_time: datetime = Field(..., description="Creation timestamp")
    last_edited_time: datetime = Field(..., description="Last edit timestamp")
    url: str = Field(..., description="Direct URL to the page")
    archived: bool = Field(default=False, description="Whether the page is archived")


class NotionPageResponse(BaseModel):
    """Response model for created Notion page.
    
    This model represents the response from the Notion API when a page is created,
    containing the essential information about the newly created page.
    
    Attributes:
        id: Unique identifier for the created page
        url: Direct URL to access the page in Notion
        created_time: Timestamp when the page was created
        properties: Page properties as returned by the API
        page: Created page details
        success: Operation success status
        message: Response message
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "87654321-4321-4321-4321-210987654321",
                "url": "https://notion.so/page/87654321432143214321210987654321",
                "created_time": "2024-01-01T00:00:00.000Z",
                "properties": {
                    "Title": {
                        "title": [{"text": {"content": "Never Gonna Give You Up"}}]
                    }
                }
            }
        }
    )

    id: str = Field(..., description="Unique page identifier")
    url: str = Field(..., description="Direct URL to the page")
    created_time: datetime = Field(..., description="Creation timestamp")
    properties: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Page properties as returned by the API"
    )
    page: NotionPage = Field(..., description="Created page details")
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Response message")