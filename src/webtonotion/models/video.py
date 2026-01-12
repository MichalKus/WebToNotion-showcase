"""Video content data models.

This module defines Pydantic models for representing video content data
extracted from various video platforms.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ContentAnalysisResult(BaseModel):
    """Structured output model for video content analysis."""

    topics: List[str] = Field(
        description="List of main topics discussed in the video", min_items=1, max_items=10
    )
    sentiment: str = Field(
        description="Overall sentiment of the video content",
        pattern="^(positive|negative|neutral)$",
    )
    locations: List[str] = Field(
        description="Geographical locations mentioned in the video",
        default_factory=list,
        max_items=20,
    )
    key_insights: List[str] = Field(
        description="Key insights or takeaways from the video", default_factory=list, max_items=10
    )
    content_category: str = Field(description="Category of the video content", default="general")


class TranscriptionResult(BaseModel):
    """Structured output model for audio transcription."""

    transcript: str = Field(description="The transcribed text from the audio")
    confidence: Optional[float] = Field(
        description="Confidence score of the transcription (0.0 to 1.0)",
        default=None,
        ge=0.0,
        le=1.0,
    )
    language: Optional[str] = Field(description="Detected language of the audio", default=None)
    processing_time: Optional[float] = Field(
        description="Time taken to process the audio in seconds", default=None, ge=0.0
    )


class VideoContent(BaseModel):
    """Represents extracted video content with metadata and analysis.

    This model contains all the information extracted from a video URL,
    including metadata, transcription, and AI-generated analysis.

    Attributes:
        url: The original video URL
        title: Video title extracted from metadata
        description: Video description from the platform
        author: Video creator/channel name
        duration: Video duration in seconds
        published_at: Video publication timestamp
        transcript: Full text transcript of the video audio
        topics: List of main topics identified in the content
        sentiment: Overall sentiment analysis result
        locations: Geographic locations mentioned in the video
        metadata: Additional platform-specific metadata
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Never Gonna Give You Up",
                "description": "The official video for Rick Astley's 'Never Gonna Give You Up'",
                "author": "Rick Astley",
                "duration": 213,
                "published_at": "2009-10-25T06:57:33Z",
                "transcript": "We're no strangers to love...",
                "topics": ["music", "80s", "pop"],
                "sentiment": "positive",
                "locations": ["London", "UK"],
                "metadata": {
                    "view_count": 1000000000,
                    "like_count": 15000000,
                    "platform": "youtube",
                },
            }
        }
    )

    url: HttpUrl = Field(..., description="Original video URL")
    title: str = Field(..., description="Video title", min_length=1)
    description: str = Field(default="", description="Video description")
    author: str = Field(..., description="Video creator/channel name", min_length=1)
    duration: float | None = Field(default=None, description="Video duration in seconds", ge=0)
    published_at: datetime | None = Field(default=None, description="Video publication timestamp")
    transcript: str = Field(default="", description="Full text transcript of the video")
    topics: list[str] = Field(default_factory=list, description="Main topics identified")
    sentiment: str = Field(default="neutral", description="Overall sentiment analysis")
    locations: list[str] = Field(default_factory=list, description="Geographic locations mentioned")
    metadata: dict[str, str | int | float | bool] = Field(
        default_factory=dict, description="Additional platform-specific metadata"
    )
