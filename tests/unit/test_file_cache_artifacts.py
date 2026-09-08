"""Per-artifact cache keys: each stage's output is stored and expires on its own."""

import asyncio
import os
import time
from unittest.mock import patch

import pytest

from webtonotion.config.settings import settings
from webtonotion.services.storage.file_cache import FileCacheService


def make_cache(tmp_path) -> FileCacheService:
    with (
        patch.object(settings, "cache_dir", str(tmp_path)),
        patch.object(settings, "enable_caching", True),
    ):
        return FileCacheService()


@pytest.mark.asyncio
async def test_artifacts_for_one_url_do_not_collide(tmp_path):
    cache = make_cache(tmp_path)
    url = "https://www.example.com/watch?v=a"

    await cache.put_artifact(url, "metadata", {"title": "A"})
    await cache.put_artifact(url, "summary:concise", {"summary": "S"})

    assert await cache.get_artifact(url, "metadata") == {"title": "A"}
    assert await cache.get_artifact(url, "summary:concise") == {"summary": "S"}


@pytest.mark.asyncio
async def test_missing_artifact_returns_none(tmp_path):
    cache = make_cache(tmp_path)
    assert await cache.get_artifact("https://www.example.com/v", "metadata") is None


@pytest.mark.asyncio
async def test_artifact_name_with_colon_is_filesystem_safe(tmp_path):
    cache = make_cache(tmp_path)
    url = "https://www.example.com/watch?v=a"

    await cache.put_artifact(url, "summary:bullet points:long", {"summary": "S"})

    path = cache.artifact_path(url, "summary:bullet points:long")
    assert path.exists()
    assert ":" not in path.name


@pytest.mark.asyncio
async def test_metadata_artifact_outlives_the_short_cache_expiration(tmp_path):
    """metadata carries the transcript, which is immutable, so it keeps the long
    transcript retention rather than the short cache_expiration analysis needs."""
    with (
        patch.object(settings, "cache_dir", str(tmp_path)),
        patch.object(settings, "enable_caching", True),
        patch.object(settings, "cache_expiration", 60),
        patch.object(settings, "transcript_ttl", 60 * 60 * 24 * 30),
    ):
        cache = FileCacheService()

    url = "https://www.example.com/watch?v=a"
    await cache.put_artifact(url, "metadata", {"title": "A"})
    await cache.put_artifact(url, "analysis", {"topics": ["x"]})

    # Age both entries well past cache_expiration but within transcript_ttl.
    old = os.path.getmtime(cache.artifact_path(url, "metadata")) - 3600
    os.utime(cache.artifact_path(url, "metadata"), (old, old))
    os.utime(cache.artifact_path(url, "analysis"), (old, old))

    assert await cache.get_artifact(url, "metadata") == {"title": "A"}
    assert await cache.get_artifact(url, "analysis") is None


@pytest.mark.asyncio
async def test_artifact_write_does_not_block_the_event_loop(tmp_path):
    """The metadata artifact embeds a full transcript, so its serialize+write must
    run off the event loop -- other coroutines have to keep making progress while
    one chat turn is persisting."""
    cache = make_cache(tmp_path)
    url = "https://www.example.com/watch?v=a"

    def slow_write(path, data):
        time.sleep(0.2)  # stand in for a large json.dump to disk
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    tick_task = asyncio.create_task(ticker())
    with patch.object(FileCacheService, "_write_json", staticmethod(slow_write)):
        await cache.put_artifact(url, "metadata", {"transcript": "x" * 1000})
    tick_task.cancel()

    # A blocking write would have frozen the loop for the whole 0.2s (0 ticks);
    # off-loop, the ticker keeps running.
    assert ticks >= 5


@pytest.mark.asyncio
async def test_a_failed_write_leaves_the_existing_artifact_intact(tmp_path):
    """The write is temp-file + os.replace: a serialization error mid-write must not
    truncate or corrupt the artifact already on disk -- losing the metadata artifact
    means re-running Whisper."""
    cache = make_cache(tmp_path)
    url = "https://www.example.com/watch?v=a"
    await cache.put_artifact(url, "metadata", {"transcript": "expensive", "v": 1})

    with patch(
        "webtonotion.services.storage.file_cache.json.dump", side_effect=RuntimeError("boom")
    ):
        await cache.put_artifact(url, "metadata", {"v": 2})  # logged, never raised

    assert await cache.get_artifact(url, "metadata") == {"transcript": "expensive", "v": 1}
    assert not list(tmp_path.glob("*.tmp"))  # temp file cleaned up


@pytest.mark.asyncio
async def test_artifact_lock_is_shared_across_instances_for_one_key(tmp_path):
    """Several FileCacheService instances exist at once (chat singleton + one per
    VideoScrapingService); they must contend on the same lock for a given file."""
    with (
        patch.object(settings, "cache_dir", str(tmp_path)),
        patch.object(settings, "enable_caching", True),
    ):
        a, b = FileCacheService(), FileCacheService()

    url = "https://www.example.com/watch?v=a"
    assert a.artifact_lock(url, "metadata") is b.artifact_lock(url, "metadata")
    assert a.artifact_lock(url, "metadata") is not a.artifact_lock(url, "analysis")


@pytest.mark.asyncio
async def test_caching_disabled_short_circuits_both_directions(tmp_path):
    cache = make_cache(tmp_path)
    cache.enable_caching = False

    await cache.put_artifact("https://www.example.com/v", "metadata", {"title": "A"})

    assert await cache.get_artifact("https://www.example.com/v", "metadata") is None
