"""yt-dlp video extractor implementation."""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp
from pydub import AudioSegment

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings
from webtonotion.exceptions import VideoScrapingError
from webtonotion.services.extraction.base import ExtractionData, VideoExtractor


class YtDlpExtractor(VideoExtractor, LoggerMixin):
    """Extracts video content using yt-dlp."""

    def __init__(self) -> None:
        """Initialize yt-dlp extractor."""
        self.cache_dir = Path(settings.cache_dir)
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True, parents=True)
        self.max_audio_duration = settings.max_video_duration
        self.verbose_logging = settings.verbose_logging

        # Configure yt-dlp options
        self.yt_dlp_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(self.cache_dir / "%(id)s.%(ext)s"),
            "extractaudio": True,
            "audioformat": "mp3",
            "audioquality": self._get_audio_quality_value(settings.audio_quality),
            "no_warnings": False,
            "quiet": False,
            "max_filesize": self._parse_file_size(settings.max_file_size),
            "verbose": self.verbose_logging,
            "remote_components": ["ejs:github"],
            "nocheckcertificate": True,
            "dump_pages": True,
            "ignoreerrors": True,
            "ignore_no_formats_error": True,
            "geo_bypass": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-us,en;q=0.5",
            },
        }

        # Add cookies file if configured
        if settings.cookies_file_path:
            cookie_path = Path(settings.cookies_file_path)
            if cookie_path.exists():
                self.yt_dlp_opts["cookiefile"] = str(cookie_path)
                self.logger.info(f"Using cookies file: {cookie_path}")
            else:
                self.logger.warning(f"Cookies file configured but not found: {cookie_path}")

    def _parse_file_size(self, size_str: str) -> int:
        """Parse file size string (e.g., '100MB') into bytes."""
        size_str = size_str.strip().upper()
        if size_str.endswith("KB"):
            return int(float(size_str.replace("KB", "")) * 1024)
        if size_str.endswith("MB"):
            return int(float(size_str.replace("MB", "")) * 1024 * 1024)
        if size_str.endswith("GB"):
            return int(float(size_str.replace("GB", "")) * 1024 * 1024 * 1024)
        return int(size_str)

    def _get_audio_quality_value(self, quality_str: str) -> int:
        """Convert audio quality string to yt-dlp compatible integer value."""
        quality_mapping = {
            "best": 0,  # Best quality (VBR)
            "good": 192,  # 192 kbps
            "medium": 128,  # 128 kbps
        }
        return quality_mapping.get(quality_str.lower(), 192)

    def _parse_upload_date(self, upload_date: Optional[str]) -> Optional[datetime]:
        """Parse upload date from yt-dlp format."""
        if not upload_date:
            return None
        try:
            return datetime.strptime(upload_date, "%Y%m%d")
        except (ValueError, TypeError):
            return None

    async def extract(self, url: str) -> ExtractionData:
        """Extract video content using yt-dlp."""
        self.logger.info(f"Extracting video metadata with use of yt-dlp")

        try:
            # Extract metadata first
            with yt_dlp.YoutubeDL(self.yt_dlp_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                raise VideoScrapingError("Failed to extract video information")

            # Log summary of extracted metadata
            info_summary = {
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "duration": info.get("duration"),
                "view_count": info.get("view_count"),
                "upload_date": info.get("upload_date"),
            }
            self.logger.info(f"Extracted video metadata: {info_summary}")

            duration = info.get("duration") or 0
            audio_path = None

            # Check duration limit
            if duration and duration > self.max_audio_duration:
                self.logger.warning(
                    f"Video duration ({duration}s) exceeds limit ({self.max_audio_duration}s)"
                )
                # We will return result without audio path, orchestrator will handle skipping transcription
            else:
                # Download audio
                download_result = await self._download_audio(url, info)
                if download_result:
                    audio_path, _ = download_result

            return ExtractionData(
                url=url,
                title=info.get("title") or "Unknown Title",
                description=info.get("description") or "",
                author=info.get("uploader") or "Unknown Author",
                duration=duration,
                published_at=self._parse_upload_date(info.get("upload_date") or ""),
                metadata={
                    "platform": info.get("extractor") or "unknown",
                    "view_count": info.get("view_count") or 0,
                    "like_count": info.get("like_count") or 0,
                    "video_id": info.get("id") or "",
                },
                audio_path=audio_path,
            )

        except Exception as e:
            self.logger.error(f"yt-dlp processing failed for {url}: {e}")
            raise VideoScrapingError(f"yt-dlp processing failed: {e}") from e

    async def _download_audio(self, url: str, info: Dict[str, Any]) -> Optional[tuple[Path, str]]:
        """Download audio from video and return path and video ID."""
        try:
            video_id = info.get("id") or hashlib.md5(url.encode()).hexdigest()[:8]
            audio_path = self.temp_dir / f"{video_id}.mp3"

            # Skip if already cached/exists in temp
            if audio_path.exists():
                self.logger.info(f"Using cached audio: {audio_path}")
                return audio_path, video_id

            opts = self.yt_dlp_opts.copy()
            opts["outtmpl"] = str(self.temp_dir / f"{video_id}.%(ext)s")
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

            try:
                self.logger.info(f"Downloading audio from video content")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                self.logger.info(f"Download completed for video content")
            except Exception as e:
                self.logger.error(f"Download failed: {e}", exc_info=True)
                raise

            # Find the downloaded file (extension might vary)
            for ext in ["mp3", "webm", "m4a", "wav"]:
                potential_path = self.temp_dir / f"{video_id}.{ext}"
                if potential_path.exists():
                    if ext != "mp3":
                        # Convert to mp3 using pydub
                        audio = AudioSegment.from_file(str(potential_path))
                        audio.export(
                            str(audio_path), format="mp3", parameters=["-ac", "1", "-ar", "16000"]
                        )
                        potential_path.unlink()  # Remove original
                    else:
                        audio_path = potential_path
                    return audio_path, video_id

            self.logger.warning(f"No audio file found after download for {url}")
            return None

        except Exception as e:
            self.logger.error(f"Audio download failed for {url}: {e}")
            return None
