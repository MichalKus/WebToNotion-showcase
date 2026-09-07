"""Audio transcription service using Groq Whisper API."""

import time
from pathlib import Path
from typing import Any

import groq
import logfire

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings
from webtonotion.exceptions import VideoScrapingError
from webtonotion.models.transcript import StoredTranscript, TranscriptSegment


def _parse_segments(raw_segments: Any) -> list[TranscriptSegment]:
    """Convert Whisper ``verbose_json`` segments into :class:`TranscriptSegment`.

    Groq returns dicts, but the SDK may hand back objects depending on version, and a
    model without segment support returns nothing at all. Anything unparseable is
    skipped rather than failing the transcription — the text is the load-bearing part;
    timestamps are an enhancement.
    """
    if not raw_segments:
        return []

    segments: list[TranscriptSegment] = []
    for raw in raw_segments:
        try:
            if isinstance(raw, dict):
                start, end, text = raw.get("start"), raw.get("end"), raw.get("text")
            else:
                start, end, text = (
                    getattr(raw, "start", None),
                    getattr(raw, "end", None),
                    getattr(raw, "text", None),
                )
            if start is None or end is None or text is None:
                continue
            segments.append(
                TranscriptSegment(start=float(start), end=float(end), text=str(text).strip())
            )
        except (TypeError, ValueError):
            continue
    return segments


class AudioTranscriber(LoggerMixin):
    """Service for transcribing audio files using Groq Whisper API."""

    def __init__(self) -> None:
        """Initialize the transcription service with direct Groq client."""
        self.groq_client = groq.AsyncGroq(
            api_key=settings.whisper_api_key, max_retries=settings.max_retries
        )
        self.cleanup_temp_files = settings.cleanup_temp_files
        self.temp_dir = Path(settings.temp_dir)

    async def transcribe(self, audio_path: Path) -> StoredTranscript:
        """Transcribe an audio file with Groq Whisper, keeping segment timestamps.

        ``verbose_json`` costs the same as ``text`` and additionally yields per-segment
        start/end times, which is what lets answers cite positions in the video.
        """
        with logfire.span("audio_transcription.transcribe") as span:
            try:
                # Log transcription request details
                span.set_attribute("audio.file_path", str(audio_path))
                span.set_attribute(
                    "audio.file_size", audio_path.stat().st_size if audio_path.exists() else 0
                )
                span.set_attribute("model.name", settings.whisper_model)
                span.set_attribute("cleanup_enabled", self.cleanup_temp_files)

                self.logger.info(
                    f"Transcribing audio: {audio_path} with Groq Whisper model: {settings.whisper_model}"
                )

                start_time = time.time()

                with logfire.span("groq_api.transcription_request") as api_span:
                    api_span.set_attribute("audio.filename", audio_path.name)
                    api_span.set_attribute("audio.format", "audio/mpeg")
                    api_span.set_attribute("model", settings.whisper_model)

                    with open(audio_path, "rb") as audio_file:
                        response = await self.groq_client.audio.transcriptions.create(
                            file=(audio_path.name, audio_file, "audio/mpeg"),
                            model=settings.whisper_model,
                            response_format="verbose_json",
                        )

                    text = (getattr(response, "text", "") or "").strip()
                    segments = _parse_segments(getattr(response, "segments", None))
                    transcript = StoredTranscript(
                        text=text,
                        language=getattr(response, "language", None),
                        duration=getattr(response, "duration", None),
                        segments=segments,
                    )

                    api_span.set_attribute("result.length", len(text))
                    api_span.set_attribute("result.has_content", bool(text))
                    api_span.set_attribute("result.segment_count", len(segments))

                processing_time = time.time() - start_time
                logfire.info(
                    "Audio transcription completed successfully",
                    processing_time=processing_time,
                    transcript_length=len(transcript.text),
                    transcript_content=transcript.text,
                    segment_count=len(transcript.segments),
                    audio_path=str(audio_path),
                )

                # Clean up temporary files if enabled
                if (
                    self.cleanup_temp_files
                    and audio_path.exists()
                    and audio_path.parent == self.temp_dir
                ):
                    audio_path.unlink()
                    self.logger.debug(f"Cleaned up temporary audio file: {audio_path}")
                    logfire.debug("Cleaned up temporary audio file", audio_path=str(audio_path))

                return transcript

            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"Audio transcription failed: {e}")
                logfire.error(
                    "Audio transcription failed",
                    error=error_msg,
                    error_type=type(e).__name__,
                    audio_path=str(audio_path),
                )

                # Clean up temporary files if enabled
                if (
                    self.cleanup_temp_files
                    and audio_path.exists()
                    and audio_path.parent == self.temp_dir
                ):
                    audio_path.unlink()
                    self.logger.debug(f"Cleaned up temporary audio file: {audio_path}")
                    logfire.debug(
                        "Cleaned up temporary audio file after error", audio_path=str(audio_path)
                    )

                raise VideoScrapingError(f"Audio transcription failed: {e}") from e
