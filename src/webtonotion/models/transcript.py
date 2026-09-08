"""Transcript data models.

Three models, split by where they travel:

- :class:`TranscriptSegment` and :class:`StoredTranscript` are the *storage* shape.
  A full transcript can run to 100k characters and never enters conversation history.
- :class:`TranscriptRef` is the *chat* shape — a handle the orchestrator can hold in
  context for a few hundred tokens. ``get_transcript`` returns this, which is what
  keeps a 50k-character transcript out of the persisted message history.
"""

import hashlib

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """One timestamped span of speech, as returned by Whisper's ``verbose_json``."""

    start: float = Field(..., description="Segment start time in seconds", ge=0)
    end: float = Field(..., description="Segment end time in seconds", ge=0)
    text: str = Field(..., description="Transcribed text for this span")


class StoredTranscript(BaseModel):
    """A full transcript with its segments — the storage-side shape.

    This is what ``AudioTranscriber.transcribe`` returns and what
    ``VideoScrapingService`` persists inside the video's ``metadata`` cache artifact.
    It is never returned from a tool.
    """

    text: str = Field(..., description="Full transcript text")
    language: str | None = Field(default=None, description="Detected language code")
    duration: float | None = Field(default=None, description="Audio duration in seconds", ge=0)
    segments: list[TranscriptSegment] = Field(
        default_factory=list, description="Timestamped segments, empty if unavailable"
    )


class TranscriptRef(BaseModel):
    """A chat-sized handle to a stored transcript.

    Returned by the ``get_transcript`` tool. The orchestrator sees this going in and a
    summary or answer coming out; the transcript body only ever enters an ephemeral
    sub-agent run.
    """

    url: str = Field(..., description="Video URL the transcript belongs to")
    transcript_hash: str = Field(..., description="Content hash of the transcript text")
    char_count: int = Field(..., description="Length of the full transcript in characters", ge=0)
    segment_count: int = Field(..., description="Number of timestamped segments", ge=0)
    duration: float | None = Field(default=None, description="Audio duration in seconds", ge=0)
    language: str | None = Field(default=None, description="Detected language code")
    preview: str = Field(default="", description="Leading excerpt of the transcript")

    @classmethod
    def from_transcript(
        cls, url: str, transcript: "StoredTranscript", preview_chars: int
    ) -> "TranscriptRef":
        """Mint the chat-sized handle for a stored transcript body.

        The body lives in the video's ``metadata`` cache artifact; this ref is all the
        orchestrator ever holds.
        """
        return cls(
            url=url,
            transcript_hash=hashlib.sha256(transcript.text.encode("utf-8")).hexdigest(),
            char_count=len(transcript.text),
            segment_count=len(transcript.segments),
            duration=transcript.duration,
            language=transcript.language,
            preview=transcript.text[:preview_chars],
        )
