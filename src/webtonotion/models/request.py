"""API request data models.

This module defines Pydantic models for validating and processing
incoming API requests to the WebToNotion application.
"""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ProcessURLRequest(BaseModel):
    """Request model for processing video URLs.

    This model validates incoming requests to process video content from
    various platforms and create corresponding Notion pages.

    Attributes:
        url: The video URL to be processed (must be a valid HTTP/HTTPS URL)
        database_id: Optional Notion database ID to override default target
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "database_id": "12345678-1234-1234-1234-123456789012",
            }
        }
    )

    url: HttpUrl = Field(
        ..., description="Video URL to process (YouTube, Instagram, Facebook, etc.)"
    )
    database_id: str | None = Field(
        default=None, description="Target Notion database ID (optional)"
    )
