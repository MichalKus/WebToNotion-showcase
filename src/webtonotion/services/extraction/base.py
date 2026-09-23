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
    async def extract_metadata(self, url: str) -> ExtractionData:
        """Resolve video metadata, without downloading the audio track.

        Args:
            url: The video URL to process

        Returns:
            ExtractionData object with the extracted metadata and no audio path
        """
        pass

    @abstractmethod
    async def fetch_audio(
        self,
        url: str,
        *,
        video_id: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> Optional[Path]:
        """Download the audio track for a video.

        Split from :meth:`extract_metadata` so a caller holding already-resolved
        metadata -- freshly extracted or served from cache -- can ask for the audio
        alone instead of paying for a second metadata round trip.

        Args:
            url: The video URL to process
            video_id: Video id from an earlier extraction, used to name the audio file
            duration: Video duration from an earlier extraction, checked against the
                extractor's maximum before downloading

        Returns:
            Path to the downloaded mp3, or None when the video is too long or no
            audio file materialises
        """
        pass
