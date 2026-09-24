"""yt-dlp video extractor implementation."""

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp
from pydub import AudioSegment

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings
from webtonotion.exceptions import VideoScrapingError
from webtonotion.services.extraction.base import ExtractionData, VideoExtractor

# Resolved info dicts keyed by URL, so the audio pass downloads straight from the formats
# the metadata pass already resolved instead of re-running the extraction. Module-level
# because extractor instances are per-request; process-local, so it only hits when both
# passes run in the same worker. Stream URLs are signed for ~6 h -- the TTL stays well
# inside that, and a stale entry just falls back to a full re-extraction.
_INFO_CACHE_TTL_SECONDS = 30 * 60
_INFO_CACHE_MAX_ENTRIES = 16
# automatic_captions alone is ~11 MB for a typical YouTube video; formats are ~15 KB.
_INFO_CACHE_DROPPED_KEYS = frozenset({"automatic_captions", "subtitles", "thumbnails", "heatmap"})
_info_cache: "OrderedDict[str, tuple[float, Dict[str, Any]]]" = OrderedDict()


def _prepare_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """Return a trimmed, sanitized copy of ``info`` fit for ``process_ie_result``."""
    trimmed = {k: v for k, v in info.items() if k not in _INFO_CACHE_DROPPED_KEYS}
    sanitized: Dict[str, Any] = yt_dlp.YoutubeDL.sanitize_info(trimmed)
    return sanitized


def _remember_info(url: str, info: Dict[str, Any]) -> None:
    """Store a prepared copy of ``info`` for a later audio download."""
    _info_cache[url] = (time.monotonic(), _prepare_info(info))
    _info_cache.move_to_end(url)
    while len(_info_cache) > _INFO_CACHE_MAX_ENTRIES:
        _info_cache.popitem(last=False)


def _take_info(url: str) -> Optional[Dict[str, Any]]:
    """Pop the cached info for ``url`` if it is still fresh.

    One-shot: the audio pass consumes it, and yt-dlp mutates the dict while downloading.
    """
    entry = _info_cache.pop(url, None)
    if entry is None:
        return None
    stored_at, info = entry
    if time.monotonic() - stored_at > _INFO_CACHE_TTL_SECONDS:
        return None
    return info


class _YtDlpLogger:
    """Route yt-dlp output into the app logger instead of stdout."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, msg: str) -> None:
        # yt-dlp sends both info and debug lines here; debug ones carry a "[debug] " prefix.
        self._logger.debug(msg)

    def info(self, msg: str) -> None:
        self._logger.debug(msg)

    def warning(self, msg: str) -> None:
        self._logger.warning(msg)

    def error(self, msg: str) -> None:
        # yt-dlp raises right after reporting, and the caller logs that exception with
        # context. A fast-path failure that the fallback recovers must not read as ERROR.
        self._logger.warning(msg)


class YtDlpExtractor(VideoExtractor, LoggerMixin):
    """Extracts video content using yt-dlp.

    Extraction runs a fast profile first and falls back to a full one:

    - fast: YouTube ``android`` client only, no watch-page fetch, no cookies. Without a
      PO Token, ``android`` is the only client serving a downloadable format (itag 18,
      ``ratebypass=yes``, unthrottled); ``web`` is SABR-only and ``mweb`` needs a token.
      It needs no JS player, so this is ~1.5 s instead of ~3-6 s. It must run without
      cookies: yt-dlp drops clients that don't support cookies once a session is
      authenticated, and ``android`` is one of them.
    - full: adds ``web`` and the watch page (age gates, clearer errors) plus the cookies
      file, for login-gated content on any platform.
    """

    def __init__(self) -> None:
        """Initialize yt-dlp extractor."""
        self.temp_dir = Path(settings.temp_dir)
        self.temp_dir.mkdir(exist_ok=True, parents=True)
        self.max_audio_duration = settings.max_video_duration
        self.verbose_logging = settings.verbose_logging

        self.audio_bitrate = self._get_audio_bitrate(settings.audio_quality)

        self.cookie_file: Optional[str] = None
        if settings.cookies_file_path:
            cookie_path = Path(settings.cookies_file_path)
            if cookie_path.exists():
                self.cookie_file = str(cookie_path)
                self.logger.info(f"Using cookies file (full profile only): {cookie_path}")
            else:
                self.logger.warning(f"Cookies file configured but not found: {cookie_path}")

        self.fast_opts = self._build_opts(fast=True)
        self.full_opts = self._build_opts(fast=False)

    def _build_opts(self, *, fast: bool) -> Dict[str, Any]:
        """Build the yt-dlp options for the fast or the full extraction profile."""
        opts: Dict[str, Any] = {
            # Audio-only where offered; otherwise the smallest sensible muxed file, not
            # a 1080p video downloaded just to strip its audio.
            "format": "bestaudio/best[height<=480]/best",
            # A watch URL carrying &list= would otherwise resolve the whole playlist/mix.
            "noplaylist": True,
            # A bare playlist URL is rejected in extract_metadata -- don't resolve every
            # entry first just to find that out.
            "extract_flat": "in_playlist",
            "logger": _YtDlpLogger(self.logger),
            "quiet": True,
            "noprogress": True,
            "verbose": self.verbose_logging,
            "max_filesize": settings.max_file_size,
            "socket_timeout": min(settings.request_timeout, 30),
            # Force IPv4 -- kept from the original throttling fix, not measured on its own.
            "source_address": "0.0.0.0",
            "retries": settings.max_retries,
            "fragment_retries": settings.max_retries,
            # Only the full profile's web client needs a JS runtime (the solver scripts
            # come from the yt-dlp-ejs package). deno ships in the Docker image.
            "js_runtimes": {"node": {}, "deno": {}},
            # Let extract_info raise with the real cause instead of returning None.
            "ignoreerrors": False,
            # When True, an unavailable/private/deleted video "succeeds" with a made-up
            # title ("youtube video #<id>") and no formats -- raise instead. A failing fast
            # profile then falls back to the full one.
            "ignore_no_formats_error": False,
        }
        if fast:
            opts["extractor_args"] = {
                "youtube": {"player_client": ["android"], "player_skip": ["webpage"]}
            }
        else:
            opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
            if self.cookie_file:
                opts["cookiefile"] = self.cookie_file
        return opts

    def _get_audio_bitrate(self, quality_str: str) -> str:
        """Map ``AUDIO_QUALITY`` to a mono 16 kHz mp3 bitrate for transcription.

        Whisper resamples to 16 kHz mono anyway, so higher rates only inflate the upload.
        Even ``best`` keeps a one-hour video under Groq's 25 MB file limit.
        """
        bitrate_mapping = {
            "best": "48k",
            "good": "32k",
            "medium": "24k",
        }
        return bitrate_mapping.get(quality_str.lower(), "32k")

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
            if info.get("_type") == "playlist":
                raise VideoScrapingError("URL points to a playlist, not a single video")

            _remember_info(url, info)

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
        """Run yt-dlp's blocking metadata resolution: fast profile, then full."""
        info: Optional[Dict[str, Any]]
        try:
            with yt_dlp.YoutubeDL(self.fast_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                return info
        except Exception as e:
            self.logger.warning(f"Fast yt-dlp extraction failed, retrying with full profile: {e}")
        with yt_dlp.YoutubeDL(self.full_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info

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

            # Downloading from a resolved info dict never re-runs the extractor, so client
            # selection doesn't apply here; the full profile only adds the cookies a
            # login-gated stream may need.
            opts = self.full_opts.copy()
            opts["outtmpl"] = str(self.temp_dir / f"{video_id}.%(ext)s")
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                }
            ]
            opts["postprocessor_args"] = {
                "extractaudio": ["-ac", "1", "-ar", "16000", "-b:a", self.audio_bitrate]
            }

            downloaded = False
            info = _take_info(url)
            if info is not None:
                self.logger.info("Downloading audio from already-resolved formats")
                try:
                    await asyncio.to_thread(self._download_from_info, opts, info)
                    downloaded = True
                except Exception as e:
                    # Expired/403 stream URL etc. -- a fresh extraction gets new ones.
                    self.logger.warning(
                        f"Download from resolved formats failed, re-extracting: {e}"
                    )
            if not downloaded:
                self.logger.info("Downloading audio from video content")
                fresh = await asyncio.to_thread(self._extract_info, url)
                if not fresh:
                    raise VideoScrapingError("Failed to extract video information")
                await asyncio.to_thread(self._download_from_info, opts, _prepare_info(fresh))
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

    def _download_from_info(self, opts: Dict[str, Any], info: Dict[str, Any]) -> None:
        """Run yt-dlp's blocking download from an already-resolved info dict."""
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.process_ie_result(info, download=True)

    def _convert_to_mp3(self, source: Path, target: Path) -> None:
        """Transcode ``source`` to a mono 16 kHz mp3 at ``target``, dropping the original."""
        audio = AudioSegment.from_file(str(source))
        audio.export(
            str(target),
            format="mp3",
            bitrate=self.audio_bitrate,
            parameters=["-ac", "1", "-ar", "16000"],
        )
        source.unlink()
