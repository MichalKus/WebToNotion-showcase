"""File-based caching service, keyed per artifact.

Cache entries are keyed ``(url_hash, artifact)``, where artifact is one of
``metadata`` (transcript + summaries), ``analysis``, or ``summary:<style>:<length>``.
Each is written the moment it is produced, so a failure in a later stage never
discards an earlier stage's expensive output.

The ``metadata`` artifact carries the video's transcript (and its cached summaries)
alongside title/author, so it expires on ``transcript_ttl`` — the transcript is
effectively immutable and re-running Whisper is the most expensive operation in the
system. Every other artifact expires on ``cache_expiration`` because prompt and model
changes should invalidate it.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings

# Artifact names are used as filename components; anything outside this set is replaced.
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

# Artifact holding the video's immutable transcript + metadata + cached summaries.
_METADATA_ARTIFACT = "metadata"


class FileCacheService(LoggerMixin):
    """Service for caching per-artifact processing output to the file system."""

    # Per-(url, artifact) locks serializing read-modify-write of one cache file.
    # Class-level, not instance-level: the app holds several FileCacheService
    # instances (the chat singleton, plus a fresh one inside every
    # VideoScrapingService), and they must contend on the same lock for a given
    # file. In-process only -- WORKERS > 1 needs OS file locking, but the atomic
    # write below still rules out corruption there, only last-write-wins.
    _artifact_locks: dict[str, asyncio.Lock] = {}

    def __init__(self) -> None:
        """Initialize the file cache service."""
        self.cache_dir = Path(settings.cache_dir)
        self.cache_dir.mkdir(exist_ok=True, parents=True)
        self.enable_caching = settings.enable_caching
        self.cache_expiration = settings.cache_expiration
        self.metadata_expiration = settings.transcript_ttl

    def get_cache_key(self, url: str) -> str:
        """Generate cache key for URL."""
        return hashlib.md5(url.encode()).hexdigest()

    def artifact_path(self, url: str, artifact: str) -> Path:
        """Return the file path backing one ``(url, artifact)`` cache entry."""
        safe_artifact = _UNSAFE_IN_FILENAME.sub("_", artifact)
        return self.cache_dir / f"{self.get_cache_key(url)}.{safe_artifact}.json"

    def _ttl_for(self, artifact: str) -> int:
        """Retention in seconds for one artifact (0 = never expire).

        ``metadata`` holds the immutable transcript, so it keeps the long
        ``transcript_ttl``; everything else expires on ``cache_expiration``.
        """
        if artifact == _METADATA_ARTIFACT:
            return self.metadata_expiration
        return self.cache_expiration

    def _is_expired(self, cache_file: Path, artifact: str) -> bool:
        """Whether ``cache_file`` is older than its artifact's TTL (0 = never)."""
        ttl = self._ttl_for(artifact)
        if ttl <= 0:
            return False
        file_age = datetime.now().timestamp() - cache_file.stat().st_mtime
        if file_age > ttl:
            self.logger.info(f"Cache expired for {cache_file.name}, age: {file_age}s")
            return True
        return False

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        """Blocking read + parse of one cache file. Run via ``asyncio.to_thread``."""
        with open(path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        return data

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        """Atomically serialize + write one cache file. Run via ``asyncio.to_thread``.

        Writes a uniquely named sibling temp file, fsyncs it, then ``os.replace``s it
        over the target -- so a reader (or a crash) never sees a half-written file, and
        losing the expensive ``metadata`` artifact to a torn write is impossible. The
        temp name must be unique because concurrent writers for one key are possible.
        """
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def artifact_lock(self, url: str, artifact: str) -> asyncio.Lock:
        """The process-wide lock for one ``(url, artifact)`` cache file.

        Use around any read-modify-write of an artifact (notably ``metadata``, which
        several code paths merge into): ``async with cache.artifact_lock(url, "metadata")``.
        Re-read the artifact *inside* the block -- a copy read before acquiring is stale.
        Not reentrant.

        ``setdefault`` is race-free here: asyncio is single-threaded and there is no
        ``await`` between the lookup and the insert.
        """
        key = self.artifact_path(url, artifact).name
        return self._artifact_locks.setdefault(key, asyncio.Lock())

    async def get_artifact(self, url: str, artifact: str) -> Optional[dict[str, Any]]:
        """Return one cached artifact, or ``None`` if absent, expired, or unreadable."""
        if not self.enable_caching:
            return None

        try:
            cache_file = self.artifact_path(url, artifact)
            if not cache_file.exists() or self._is_expired(cache_file, artifact):
                return None
            data = await asyncio.to_thread(self._read_json, cache_file)
            self.logger.info(f"Cache hit for artifact '{artifact}' of URL: {url}")
            return data
        except Exception as e:
            self.logger.warning(f"Failed to load cached artifact '{artifact}': {e}")
            return None

    async def put_artifact(self, url: str, artifact: str, data: dict[str, Any]) -> None:
        """Write one artifact to the cache. Failures are logged, never raised."""
        if not self.enable_caching:
            return

        try:
            cache_file = self.artifact_path(url, artifact)
            await asyncio.to_thread(self._write_json, cache_file, data)
            self.logger.info(f"Cached artifact '{artifact}' for URL: {url}")
        except Exception as e:
            self.logger.warning(f"Failed to cache artifact '{artifact}': {e}")
