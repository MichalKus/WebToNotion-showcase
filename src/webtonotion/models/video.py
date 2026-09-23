"""Video content data models.

This module defines the Pydantic model used to shape video content data
for writing to Notion.
"""

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class VideoPageContent(BaseModel):
    """Bounded DTO for saving video content to Notion.

    This is the minimal, focused model that the Notion mapper receives,
    containing only the fields needed for the write operation.
    """

    url: HttpUrl = Field(..., description="Original video URL")
    title: str = Field(..., description="Video title")
    author: str = Field(default="", description="Video creator or channel name")
    description: str = Field(default="", description="Video description from the platform")
    duration: float | None = Field(default=None, description="Video duration in seconds", ge=0)
    published_at: datetime | None = Field(default=None, description="Video publication timestamp")
    platform: str = Field(
        default="unknown", description="Source platform (e.g. 'youtube', 'vimeo')"
    )
    language: str | None = Field(default=None, description="Detected language of the video")
    summary: str = Field(default="", description="AI-generated summary of the video content")
    transcript_excerpt: str = Field(
        default="", description="Brief excerpt from the video transcript"
    )
