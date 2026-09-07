"""Base class for video extractors."""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from webtonotion.models.transcript import StoredTranscript


class ExtractionData(BaseModel):
    """Intermediate data extracted from video source.

    Persisted as the ``metadata`` cache artifact: one JSON file per video holding its
    title/author, its cached ``summaries``, and -- once transcribed -- its full
    ``transcript`` with timestamped segments.
    """

    url: str
    title: str
    description: str
    author: str
    duration: Optional[float] = None
    published_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}
    audio_path: Optional[Path] = None
    summaries: Dict[str, str] = Field(
        default_factory=dict,
        description="Cached summaries keyed by '{style}:{length}'",
    )
    transcript: Optional[StoredTranscript] = Field(
        default=None,
        description="Full transcript with timestamped segments, once transcribed",
    )


class VideoExtractor(ABC):
    """Abstract base class for video extraction strategies."""

    @abstractmethod
    async def extract(self, url: str, download_audio: bool = True) -> ExtractionData:
        """Extract video content from URL.

        Args:
            url: The video URL to process
            download_audio: Whether to download the audio track for transcription

        Returns:
            ExtractionData object with extracted metadata and optional audio path
        """
        pass
