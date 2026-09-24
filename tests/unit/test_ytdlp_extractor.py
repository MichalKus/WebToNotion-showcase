"""Tests for YtDlpExtractor's extraction profiles and resolved-info cache.

The metadata pass stores yt-dlp's resolved info dict so the audio pass can download from
it (``process_ie_result``) instead of re-running the extraction. Extraction itself tries a
fast profile and falls back to a full one. The blocking yt-dlp calls are patched out;
these tests pin which path each pass takes.
"""

from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import pytest

from webtonotion.config.settings import settings
from webtonotion.exceptions import VideoScrapingError
from webtonotion.services.extraction import ytdlp_extractor
from webtonotion.services.extraction.ytdlp_extractor import YtDlpExtractor

URL = "https://www.youtube.com/watch?v=abc123"


def make_info(**overrides: Any) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "id": "abc123",
        "title": "Test Video",
        "uploader": "Test Author",
        "duration": 120,
        "extractor": "youtube",
        "formats": [{"format_id": "18", "url": "https://example.invalid/stream"}],
        "automatic_captions": {"en": [{"url": "https://example.invalid/captions"}]},
        "subtitles": {},
        "thumbnails": [{"url": "https://example.invalid/thumb.jpg"}],
        "heatmap": [],
    }
    info.update(overrides)
    return info


@pytest.fixture(autouse=True)
def clear_info_cache() -> Iterator[None]:
    ytdlp_extractor._info_cache.clear()
    yield
    ytdlp_extractor._info_cache.clear()


@pytest.fixture
def extractor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> YtDlpExtractor:
    monkeypatch.setattr(settings, "temp_dir", str(tmp_path))
    monkeypatch.setattr(settings, "cookies_file_path", None)
    return YtDlpExtractor()


def write_mp3(extractor: YtDlpExtractor) -> Any:
    """Side effect for a patched download: produce the mp3 yt-dlp would have written."""

    def _write(*_args: Any, **_kwargs: Any) -> None:
        (extractor.temp_dir / "abc123.mp3").write_bytes(b"mp3")

    return _write


@pytest.mark.asyncio
async def test_audio_pass_reuses_info_from_metadata_pass(extractor: YtDlpExtractor) -> None:
    with (
        patch.object(extractor, "_extract_info", return_value=make_info()) as extract,
        patch.object(
            extractor, "_download_from_info", side_effect=write_mp3(extractor)
        ) as from_info,
    ):
        data = await extractor.extract_metadata(URL)
        path = await extractor.fetch_audio(URL, video_id="abc123", duration=data.duration)

    assert path == extractor.temp_dir / "abc123.mp3"
    extract.assert_called_once()  # metadata pass only -- no second extraction
    from_info.assert_called_once()

    info = from_info.call_args.args[1]
    assert info["formats"][0]["format_id"] == "18"
    for key in ("automatic_captions", "subtitles", "thumbnails", "heatmap"):
        assert key not in info


@pytest.mark.asyncio
async def test_cached_info_is_consumed_once(extractor: YtDlpExtractor) -> None:
    with patch.object(extractor, "_extract_info", return_value=make_info()):
        await extractor.extract_metadata(URL)

    assert ytdlp_extractor._take_info(URL) is not None
    assert ytdlp_extractor._take_info(URL) is None


@pytest.mark.asyncio
async def test_audio_pass_without_metadata_pass_extracts_then_downloads(
    extractor: YtDlpExtractor,
) -> None:
    with (
        patch.object(extractor, "_extract_info", return_value=make_info()) as extract,
        patch.object(
            extractor, "_download_from_info", side_effect=write_mp3(extractor)
        ) as from_info,
    ):
        path = await extractor.fetch_audio(URL, video_id="abc123")

    assert path is not None
    extract.assert_called_once_with(URL)
    from_info.assert_called_once()
    assert "automatic_captions" not in from_info.call_args.args[1]


@pytest.mark.asyncio
async def test_expired_info_is_not_reused(extractor: YtDlpExtractor) -> None:
    with patch.object(extractor, "_extract_info", return_value=make_info()):
        await extractor.extract_metadata(URL)

    stored_at, info = ytdlp_extractor._info_cache[URL]
    ytdlp_extractor._info_cache[URL] = (
        stored_at - ytdlp_extractor._INFO_CACHE_TTL_SECONDS - 1,
        info,
    )

    with (
        patch.object(extractor, "_extract_info", return_value=make_info()) as extract,
        patch.object(extractor, "_download_from_info", side_effect=write_mp3(extractor)),
    ):
        path = await extractor.fetch_audio(URL, video_id="abc123")

    assert path is not None
    extract.assert_called_once_with(URL)


@pytest.mark.asyncio
async def test_failed_download_from_cached_info_re_extracts(extractor: YtDlpExtractor) -> None:
    download_calls: List[Dict[str, Any]] = []

    def flaky_download(_opts: Dict[str, Any], info: Dict[str, Any]) -> None:
        download_calls.append(info)
        if len(download_calls) == 1:
            raise RuntimeError("HTTP Error 403: Forbidden")
        write_mp3(extractor)()

    with (
        patch.object(extractor, "_extract_info", return_value=make_info()) as extract,
        patch.object(extractor, "_download_from_info", side_effect=flaky_download),
    ):
        await extractor.extract_metadata(URL)
        path = await extractor.fetch_audio(URL, video_id="abc123")

    assert path == extractor.temp_dir / "abc123.mp3"
    assert len(download_calls) == 2
    assert extract.call_count == 2  # metadata pass + re-extraction after the 403


def test_info_cache_is_bounded() -> None:
    for i in range(ytdlp_extractor._INFO_CACHE_MAX_ENTRIES + 5):
        ytdlp_extractor._remember_info(f"{URL}&i={i}", make_info())

    assert len(ytdlp_extractor._info_cache) == ytdlp_extractor._INFO_CACHE_MAX_ENTRIES
    # Oldest entries are evicted first.
    assert f"{URL}&i=0" not in ytdlp_extractor._info_cache
    assert f"{URL}&i={ytdlp_extractor._INFO_CACHE_MAX_ENTRIES + 4}" in ytdlp_extractor._info_cache


@pytest.mark.asyncio
async def test_playlist_url_is_rejected(extractor: YtDlpExtractor) -> None:
    playlist = {"_type": "playlist", "id": "PL123", "title": "Some playlist", "entries": []}
    with patch.object(extractor, "_extract_info", return_value=playlist):
        with pytest.raises(VideoScrapingError, match="playlist"):
            await extractor.extract_metadata(URL)

    assert URL not in ytdlp_extractor._info_cache


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL, recording the opts of every instance."""

    instances: List[Dict[str, Any]] = []
    fail_fast = True

    def __init__(self, opts: Dict[str, Any]) -> None:
        self.opts = opts
        FakeYoutubeDL.instances.append(opts)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def extract_info(self, url: str, download: bool = False) -> Dict[str, Any]:
        player_skip = self.opts["extractor_args"]["youtube"].get("player_skip")
        if player_skip and FakeYoutubeDL.fail_fast:
            raise RuntimeError("fast profile failed")
        return make_info()


@pytest.fixture
def fake_ydl() -> Iterator[type[FakeYoutubeDL]]:
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.fail_fast = True
    with patch.object(ytdlp_extractor.yt_dlp, "YoutubeDL", FakeYoutubeDL):
        yield FakeYoutubeDL


def test_extract_info_uses_fast_profile_when_it_succeeds(
    extractor: YtDlpExtractor, fake_ydl: type[FakeYoutubeDL]
) -> None:
    fake_ydl.fail_fast = False

    assert extractor._extract_info(URL) is not None
    assert fake_ydl.instances == [extractor.fast_opts]


def test_extract_info_falls_back_to_full_profile(
    extractor: YtDlpExtractor, fake_ydl: type[FakeYoutubeDL]
) -> None:
    assert extractor._extract_info(URL) is not None
    assert fake_ydl.instances == [extractor.fast_opts, extractor.full_opts]


def test_cookies_only_reach_the_full_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "temp_dir", str(tmp_path))
    monkeypatch.setattr(settings, "cookies_file_path", str(cookie_file))

    extractor = YtDlpExtractor()

    # An authenticated session makes yt-dlp drop the android client, the only one that
    # serves a downloadable YouTube format without a PO Token.
    assert "cookiefile" not in extractor.fast_opts
    assert extractor.fast_opts["extractor_args"]["youtube"]["player_client"] == ["android"]
    assert extractor.full_opts["cookiefile"] == str(cookie_file)


def test_both_profiles_resolve_single_videos_and_raise_on_errors(
    extractor: YtDlpExtractor,
) -> None:
    for opts in (extractor.fast_opts, extractor.full_opts):
        assert opts["noplaylist"] is True
        assert opts["ignoreerrors"] is False
        # True would turn an unavailable video into metadata with a made-up title.
        assert opts["ignore_no_formats_error"] is False
