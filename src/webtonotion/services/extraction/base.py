"""Base class for video extractors."""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel


class ExtractionData(BaseModel):
    """Intermediate data extracted from video source."""

    url: str
    title: str
    description: str
    author: str
    duration: Optional[float] = None
    published_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}
    audio_path: Optional[Path] = None


class VideoExtractor(ABC):
    """Abstract base class for video extraction strategies."""

    @abstractmethod
    async def extract(self, url: str) -> ExtractionData:
        """Extract video content from URL.

        Args:
            url: The video URL to process

        Returns:
            ExtractionData object with extracted metadata and optional audio path
        """
        pass
