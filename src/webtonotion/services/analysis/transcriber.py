"""Audio transcription service using Groq Whisper API."""

import time
from pathlib import Path

import groq
import logfire

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings
from webtonotion.exceptions import VideoScrapingError


class AudioTranscriber(LoggerMixin):
    """Service for transcribing audio files using Groq Whisper API."""

    def __init__(self) -> None:
        """Initialize the transcription service with direct Groq client."""
        self.groq_client = groq.AsyncGroq(api_key=settings.whisper_api_key)
        self.cleanup_temp_files = settings.cleanup_temp_files
        self.temp_dir = Path(settings.temp_dir)

    async def transcribe(self, audio_path: Path) -> str:
        """Transcribe audio file using Groq Whisper API directly."""
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
                            response_format="text",
                        )

                    transcription_length = len(response.strip()) if response else 0
                    api_span.set_attribute("result.length", transcription_length)
                    api_span.set_attribute(
                        "result.has_content", bool(response and response.strip())
                    )

                processing_time = time.time() - start_time
                logfire.info(
                    "Audio transcription completed successfully",
                    processing_time=processing_time,
                    transcript_length=len(response.strip()) if response else 0,
                    transcript_content=response.strip(),
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

                return response.strip()

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
