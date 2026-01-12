"""File-based caching service."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings
from webtonotion.models.video import VideoContent


class FileCacheService(LoggerMixin):
    """Service for caching video content to file system."""

    def __init__(self) -> None:
        """Initialize the file cache service."""
        self.cache_dir = Path(settings.cache_dir)
        self.cache_dir.mkdir(exist_ok=True, parents=True)
        self.enable_caching = settings.enable_caching
        self.cache_expiration = settings.cache_expiration

    def get_cache_key(self, url: str) -> str:
        """Generate cache key for URL."""
        return hashlib.md5(url.encode()).hexdigest()

    async def get_cached_content(self, url: str) -> Optional[VideoContent]:
        """Retrieve cached content if available and not expired."""
        if not self.enable_caching:
            return None

        try:
            cache_key = self.get_cache_key(url)
            cache_file = self.cache_dir / f"{cache_key}.json"
            if not cache_file.exists():
                return None

            # Check cache expiration if set
            if self.cache_expiration > 0:
                file_age = datetime.now().timestamp() - cache_file.stat().st_mtime
                if file_age > self.cache_expiration:
                    self.logger.info(f"Cache expired for key: {cache_key}, age: {file_age}s")
                    return None

            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.logger.info(f"Retrieved cached content for URL: {url}")
            return VideoContent(**data)
        except Exception as e:
            self.logger.warning(f"Failed to load cached content: {e}")
        return None

    async def cache_content(self, url: str, content: VideoContent) -> None:
        """Cache video content."""
        if not self.enable_caching:
            return

        try:
            cache_key = self.get_cache_key(url)
            cache_file = self.cache_dir / f"{cache_key}.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(content.model_dump(), f, ensure_ascii=False, indent=2, default=str)
            self.logger.info(f"Cached content for URL: {url}")
        except Exception as e:
            self.logger.warning(f"Failed to cache content: {e}")
