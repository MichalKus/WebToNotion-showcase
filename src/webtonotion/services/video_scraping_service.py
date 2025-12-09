"""Video scraping service for extracting content from video URLs.

This module provides comprehensive video content extraction capabilities
using yt-dlp for primary extraction, OpenAI Whisper for transcription,
and Playwright as a fallback mechanism.
"""

import json
from venv import logger

from pydantic import HttpUrl

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings
from webtonotion.exceptions import VideoScrapingError
from webtonotion.models.video import VideoContent
from webtonotion.services.analysis.content_analyzer import ContentAnalyzer
from webtonotion.services.analysis.transcriber import AudioTranscriber
from webtonotion.services.extraction.playwright_extractor import PlaywrightExtractor
from webtonotion.services.extraction.ytdlp_extractor import YtDlpExtractor
from webtonotion.services.storage.file_cache import FileCacheService


class VideoScrapingService(LoggerMixin):
    """Service for extracting comprehensive content from video URLs.

    This service uses yt-dlp as the primary method for downloading video metadata
    and audio, with Playwright as a fallback for protected content. It includes
    audio transcription and AI-powered content analysis using modern PydanticAI
    structured outputs.
    """

    def __init__(self) -> None:
        """Initialize the video scraping service."""
        # Initialize clients and sub-services
        self.file_cache = FileCacheService()
        self.ytdlp_extractor = YtDlpExtractor()
        self.playwright_extractor = PlaywrightExtractor()
        self.transcriber = AudioTranscriber()
        self.analyzer = ContentAnalyzer()

        self.logger.info(
            "VideoScrapingService initialized successfully with modern PydanticAI structured outputs"
        )

    async def process_video(self, url: HttpUrl) -> VideoContent:
        """Process a video URL and extract comprehensive content.

        Args:
            url: Video URL to process

        Returns:
            VideoContent with extracted information

        Raises:
            VideoScrapingError: If video processing fails
        """
        url_str = str(url)
        self.logger.info(f"Starting video processing for URL: {url_str}")

        try:
            # Check cache first
            cached_content = await self.file_cache.get_cached_content(url_str)
            if cached_content:
                return cached_content

            extraction_data = None

            # Try yt-dlp first
            try:
                self.logger.info(f"Attempting yt-dlp extraction for URL: {url_str}")
                extraction_data = await self.ytdlp_extractor.extract(url_str)
                self.logger.info(f"Successfully extracted content with yt-dlp for URL: {url_str}")
            except Exception as e:
                self.logger.warning(f"yt-dlp extraction failed for {url_str}: {e}")
                # Fallback logic (currently disabled as in original code)
                # self.logger.info(f"Falling back to Playwright extraction for URL: {url_str}")
                # extraction_data = await self.playwright_extractor.extract(url_str)
                # self.logger.info(f"Successfully extracted content with Playwright for URL: {url_str}")

                # If fallback is not enabled, re-raise the exception
                if not extraction_data:
                    raise

            # Transcribe audio if available
            transcript = ""
            if extraction_data.audio_path and extraction_data.audio_path.exists():
                try:
                    transcript = await self.transcriber.transcribe(extraction_data.audio_path)
                    self.logger.info(f"Successfully transcribed audio: {transcript}")

                    # Save transcription to temp file (replicating original behavior)
                    video_id = extraction_data.metadata.get("video_id")
                    if video_id:
                        transcript_file = self.transcriber.temp_dir / f"{video_id}_transcript.txt"
                        transcript_file.write_text(transcript, encoding="utf-8")
                        self.logger.debug(f"Saved transcription to {transcript_file}")

                    self.logger.info(f"Successfully transcribed audio for: {url_str}")
                except Exception as e:
                    self.logger.warning(f"Transcription failed for {url_str}: {e}")
                    # Audio path cleanup is handled by transcriber on error

            # Analyze content with AI
            info_for_analysis = {
                "title": extraction_data.title,
                "description": extraction_data.description,
                "extractor": extraction_data.metadata.get("platform", "unknown"),
            }
            analyzed_content = await self.analyzer.analyze(info_for_analysis, transcript)

            # Construct final VideoContent
            video_content = VideoContent(
                url=url,
                title=extraction_data.title,
                description=extraction_data.description,
                author=extraction_data.author,
                duration=extraction_data.duration,
                published_at=extraction_data.published_at,
                transcript=transcript,
                topics=analyzed_content.topics,
                sentiment=analyzed_content.sentiment,
                locations=analyzed_content.locations,
                metadata={
                    **extraction_data.metadata,
                    "key_insights": json.dumps(
                        analyzed_content.key_insights
                    ),  # Convert list to JSON string
                    "content_category": analyzed_content.content_category,
                    # Add skipped_transcription if applicable
                    **(
                        {"skipped_transcription": "duration_exceeded"}
                        if (
                            extraction_data.duration
                            and extraction_data.duration > self.ytdlp_extractor.max_audio_duration
                            and not transcript
                        )
                        else {}
                    ),
                },
            )

            # Cache the result
            await self.file_cache.cache_content(url_str, video_content)

            return video_content

        except Exception as e:
            self.logger.error(f"Video processing failed for URL {url_str}: {e}", exc_info=True)
            raise VideoScrapingError(f"Failed to process video: {e}") from e
