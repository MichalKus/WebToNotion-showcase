"""yt-dlp video extractor implementation."""

import asyncio
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
            "max_filesize": settings.max_file_size,
            "socket_timeout": settings.request_timeout,
            "verbose": self.verbose_logging,
            "retries": settings.max_retries,
            "fragment_retries": settings.max_retries,
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

    async def extract_metadata(self, url: str) -> ExtractionData:
        """Resolve video metadata using yt-dlp, without downloading the audio track.

        Args:
            url: The video URL to process.
        """
        self.logger.info("Extracting video metadata with use of yt-dlp")

        try:
            info = await asyncio.to_thread(self._extract_info, url)

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

            return ExtractionData(
                url=url,
                title=info.get("title") or "Unknown Title",
                description=info.get("description") or "",
                author=info.get("uploader") or "Unknown Author",
                duration=info.get("duration") or 0,
                published_at=self._parse_upload_date(info.get("upload_date") or ""),
                metadata={
                    "platform": info.get("extractor") or "unknown",
                    "view_count": info.get("view_count") or 0,
                    "like_count": info.get("like_count") or 0,
                    "video_id": info.get("id") or "",
                },
                audio_path=None,
            )

        except VideoScrapingError:
            raise
        except Exception as e:
            self.logger.error(f"yt-dlp processing failed for {url}: {e}")
            raise VideoScrapingError(f"yt-dlp processing failed: {e}") from e

    def _extract_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Run yt-dlp's blocking metadata resolution."""
        with yt_dlp.YoutubeDL(self.yt_dlp_opts) as ydl:
            return ydl.extract_info(url, download=False)

    async def fetch_audio(
        self,
        url: str,
        *,
        video_id: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> Optional[Path]:
        """Download the audio track for ``url``.

        ``video_id`` and ``duration`` come from an earlier :meth:`extract_metadata`
        call -- or from its cached artifact -- so a caller that already resolved the
        video does not pay for a second metadata round trip.
        """
        if duration and duration > self.max_audio_duration:
            self.logger.warning(
                f"Video duration ({duration}s) exceeds limit ({self.max_audio_duration}s)"
            )
            # Return without an audio path; the caller decides how to report the skip.
            return None

        return await self._download_audio(
            url, video_id or hashlib.md5(url.encode()).hexdigest()[:8]
        )

    async def _download_audio(self, url: str, video_id: str) -> Optional[Path]:
        """Download audio for ``video_id`` and return the path to the mp3."""
        try:
            audio_path = self.temp_dir / f"{video_id}.mp3"

            # Skip if already cached/exists in temp
            if audio_path.exists():
                self.logger.info(f"Using cached audio: {audio_path}")
                return audio_path

            opts = self.yt_dlp_opts.copy()
            opts["outtmpl"] = str(self.temp_dir / f"{video_id}.%(ext)s")
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

            self.logger.info("Downloading audio from video content")
            await asyncio.to_thread(self._download, opts, url)
            self.logger.info("Download completed for video content")

            # Find the downloaded file (extension might vary)
            for ext in ["mp3", "webm", "m4a", "wav"]:
                potential_path = self.temp_dir / f"{video_id}.{ext}"
                if not potential_path.exists():
                    continue
                if ext == "mp3":
                    return potential_path
                await asyncio.to_thread(self._convert_to_mp3, potential_path, audio_path)
                return audio_path

            self.logger.warning(f"No audio file found after download for {url}")
            return None

        except Exception as e:
            self.logger.error(f"Audio download failed for {url}: {e}", exc_info=True)
            return None

    def _download(self, opts: Dict[str, Any], url: str) -> None:
        """Run yt-dlp's blocking download."""
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    def _convert_to_mp3(self, source: Path, target: Path) -> None:
        """Transcode ``source`` to a mono 16 kHz mp3 at ``target``, dropping the original."""
        audio = AudioSegment.from_file(str(source))
        audio.export(str(target), format="mp3", parameters=["-ac", "1", "-ar", "16000"])
        source.unlink()
