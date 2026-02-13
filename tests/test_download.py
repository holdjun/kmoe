"""Tests for kmoe.download module."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from kmoe.constants import DownloadFormat
from kmoe.download import (
    download_volume,
    download_volumes,
    get_download_urls,
    resolve_format,
)
from kmoe.exceptions import DownloadError, NetworkError
from kmoe.library import add_downloaded_volume, load_entry, save_entry
from kmoe.models import AppConfig, ComicDetail, ComicMeta, DownloadedVolume, LibraryEntry, Volume

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(book_id: str = "18488", comic_id: str = "abc123") -> ComicMeta:
    return ComicMeta(book_id=book_id, comic_id=comic_id, title="Test Comic")


def _volume(
    vol_id: str = "1001",
    title: str = "Vol 01",
    size_epub_mb: float = 0.0,
    size_mobi_mb: float = 0.0,
) -> Volume:
    return Volume(vol_id=vol_id, title=title, size_epub_mb=size_epub_mb, size_mobi_mb=size_mobi_mb)


def _detail(volumes: list[Volume] | None = None, **kw: str) -> ComicDetail:
    return ComicDetail(meta=_meta(**kw), volumes=volumes or [_volume()])


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(download_dir=tmp_path, rate_limit_delay=0, max_retries=1)


def _mock_client(
    urls: list[str] | None = None,
    get_url_side_effect: list[Exception | str] | None = None,
    download_side_effect: list[Exception | Path] | None = None,
) -> AsyncMock:
    """Build a mock KmoeClient."""
    client = AsyncMock()

    if get_url_side_effect is not None:
        client.get_download_url.side_effect = list(get_url_side_effect)
    elif urls is not None:
        client.get_download_url.side_effect = urls

    if download_side_effect is not None:

        async def _download(_url: str, dest: Path, **_kw: object) -> Path:
            effect = download_side_effect.pop(0)
            if isinstance(effect, Exception):
                raise effect
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x" * 1024)
            return dest

        client.download_file.side_effect = _download
    else:

        async def _download_ok(_url: str, dest: Path, **_kw: object) -> Path:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x" * 1024)
            return dest

        client.download_file.side_effect = _download_ok

    return client


# ---------------------------------------------------------------------------
# resolve_format
# ---------------------------------------------------------------------------


class TestResolveFormat:
    def test_valid_formats(self) -> None:
        """Given valid format strings, then the correct enum is returned."""
        assert resolve_format("epub") == DownloadFormat.EPUB
        assert resolve_format("MOBI") == DownloadFormat.MOBI

    def test_invalid_format_raises(self) -> None:
        """Given an unknown format string, then DownloadError is raised."""
        with pytest.raises(DownloadError):
            resolve_format("pdf")


# ---------------------------------------------------------------------------
# get_download_urls
# ---------------------------------------------------------------------------


class TestGetDownloadUrls:
    """Given a client and volume info, get_download_urls tries multiple lines."""

    async def test_returns_urls_from_both_lines(self) -> None:
        """When both lines succeed, then two URLs are returned."""
        client = _mock_client(urls=["https://cdn1/file.epub", "https://cdn2/file.epub"])
        urls = await get_download_urls(client, "18488", "1001", DownloadFormat.EPUB)
        assert len(urls) == 2
        assert client.get_download_url.call_count == 2

    async def test_returns_partial_when_one_line_fails(self) -> None:
        """When one line fails and the other succeeds, then one URL is returned."""
        client = _mock_client(
            get_url_side_effect=[NetworkError("line 0 down"), "https://cdn2/file.epub"]
        )
        urls = await get_download_urls(client, "18488", "1001", DownloadFormat.EPUB)
        assert urls == ["https://cdn2/file.epub"]

    async def test_raises_when_all_lines_fail(self) -> None:
        """When all lines fail, then DownloadError is raised."""
        client = _mock_client(get_url_side_effect=[NetworkError("fail 0"), NetworkError("fail 1")])
        with pytest.raises(DownloadError, match="all lines"):
            await get_download_urls(client, "18488", "1001", DownloadFormat.EPUB)

    async def test_passes_line_number_to_client(self) -> None:
        """When called with default lines (0, 1), then line= is passed correctly."""
        client = _mock_client(urls=["https://cdn1/a", "https://cdn2/b"])
        await get_download_urls(client, "18488", "1001", DownloadFormat.EPUB)
        calls = client.get_download_url.call_args_list
        assert calls[0].kwargs["line"] == 0
        assert calls[1].kwargs["line"] == 1


# ---------------------------------------------------------------------------
# download_volume — skip logic
# ---------------------------------------------------------------------------


def _seed_entry(
    config: AppConfig,
    detail: ComicDetail,
    vol: Volume,
    comic_id: str = "abc123",
) -> None:
    """Pre-populate a library entry with one downloaded volume record."""
    entry = LibraryEntry(book_id="18488", comic_id=comic_id, title="Test Comic", meta=detail.meta)
    save_entry(config, entry, update_index=False)
    dv = DownloadedVolume(
        vol_id=vol.vol_id,
        title=vol.title,
        format="epub",
        filename="[Kmoe][Test Comic]Vol 01.epub",
        downloaded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    add_downloaded_volume(config, entry, dv, update_index=False)


class TestDownloadVolumeSkip:
    """Given a volume that was previously downloaded."""

    async def test_skips_when_recorded_and_file_exists(self, tmp_path: Path) -> None:
        """When library records the volume and the file exists on disk,
        then the download is skipped."""
        config = _config(tmp_path)
        detail = _detail()
        _seed_entry(config, detail, detail.volumes[0])

        from kmoe.library import get_comic_dir

        dest = get_comic_dir(config, "abc123", "Test Comic") / "[Kmoe][Test Comic]Vol 01.epub"
        dest.write_bytes(b"x" * 1024)

        client = _mock_client()
        result = await download_volume(client, config, detail, "1001", DownloadFormat.EPUB)
        assert result.skipped is True
        client.get_download_url.assert_not_called()

    async def test_does_not_skip_when_file_missing(self, tmp_path: Path) -> None:
        """When library records the volume but the file is missing on disk,
        then the volume is re-downloaded."""
        config = _config(tmp_path)
        detail = _detail()
        _seed_entry(config, detail, detail.volumes[0])

        client = _mock_client(urls=["https://cdn/a", "https://cdn/b"])
        result = await download_volume(client, config, detail, "1001", DownloadFormat.EPUB)
        assert result.skipped is False

    async def test_does_not_skip_when_size_mismatch(self, tmp_path: Path) -> None:
        """When the file exists but its size deviates >10MB from expected,
        then the volume is re-downloaded."""
        config = _config(tmp_path)
        vol = _volume(size_epub_mb=50.0)
        detail = _detail(volumes=[vol])
        _seed_entry(config, detail, vol)

        from kmoe.library import get_comic_dir

        dest = get_comic_dir(config, "abc123", "Test Comic") / "[Kmoe][Test Comic]Vol 01.epub"
        dest.write_bytes(b"x" * 100)  # ~0 MB vs expected 50 MB

        client = _mock_client(urls=["https://cdn/a", "https://cdn/b"])
        result = await download_volume(client, config, detail, "1001", DownloadFormat.EPUB)
        assert result.skipped is False


# ---------------------------------------------------------------------------
# download_volume — multi-URL fallback
# ---------------------------------------------------------------------------


class TestDownloadVolumeFallback:
    """Given multiple CDN URLs obtained from different lines."""

    async def test_succeeds_on_second_url_when_first_fails(self, tmp_path: Path) -> None:
        """When the first CDN URL fails, then the second URL is tried and succeeds."""
        config = _config(tmp_path)
        client = _mock_client(
            urls=["https://cdn1/file.epub", "https://cdn2/file.epub"],
            download_side_effect=[NetworkError("cdn1 down"), tmp_path],
        )
        result = await download_volume(client, config, _detail(), "1001", DownloadFormat.EPUB)
        assert result.skipped is False
        assert result.size_bytes > 0

    async def test_raises_when_all_urls_fail(self, tmp_path: Path) -> None:
        """When all CDN URLs fail, then DownloadError is raised."""
        config = _config(tmp_path)
        client = _mock_client(
            urls=["https://cdn1/file.epub", "https://cdn2/file.epub"],
            download_side_effect=[NetworkError("cdn1"), NetworkError("cdn2")],
        )
        with pytest.raises(DownloadError):
            await download_volume(client, config, _detail(), "1001", DownloadFormat.EPUB)


# ---------------------------------------------------------------------------
# download_volume — library record dedup
# ---------------------------------------------------------------------------


class TestDownloadVolumeDedup:
    """Given a volume that is re-downloaded."""

    async def test_no_duplicate_records_on_redownload(self, tmp_path: Path) -> None:
        """When a volume is downloaded twice, then only one record exists."""
        config = _config(tmp_path)
        detail = _detail()
        client = _mock_client(urls=["https://cdn/a", "https://cdn/b"])

        await download_volume(client, config, detail, "1001", DownloadFormat.EPUB)
        # Second download — client needs fresh URLs
        client.get_download_url.side_effect = ["https://cdn/a", "https://cdn/b"]
        await download_volume(client, config, detail, "1001", DownloadFormat.EPUB)

        entry = load_entry(config, "abc123", "Test Comic")
        assert entry is not None
        epub_records = [
            v for v in entry.downloaded_volumes if v.vol_id == "1001" and v.format == "epub"
        ]
        assert len(epub_records) == 1


# ---------------------------------------------------------------------------
# download_volumes — batch behavior
# ---------------------------------------------------------------------------


class TestDownloadVolumes:
    """Given multiple volume IDs to download."""

    async def test_successful_batch(self, tmp_path: Path) -> None:
        """When all volumes succeed, then results contain all volumes and no errors."""
        config = _config(tmp_path)
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        detail = _detail(volumes=vols)
        client = _mock_client(urls=["https://cdn/a"] * 4)

        batch = await download_volumes(
            client, config, detail, ["1001", "1002"], DownloadFormat.EPUB
        )
        assert len(batch.results) == 2
        assert len(batch.errors) == 0

    async def test_partial_failure(self, tmp_path: Path) -> None:
        """When one volume fails, then it appears in errors while others succeed."""
        config = _config(tmp_path)
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        detail = _detail(volumes=vols)

        async def _get_url(**kwargs: object) -> str:
            if kwargs["vol_id"] == "1002":
                raise NetworkError("fail")
            return "https://cdn/ok"

        client = AsyncMock()
        client.get_download_url.side_effect = _get_url

        async def _download_ok(_url: str, dest: Path, **_kw: object) -> Path:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x" * 1024)
            return dest

        client.download_file.side_effect = _download_ok

        batch = await download_volumes(
            client, config, detail, ["1001", "1002"], DownloadFormat.EPUB
        )
        assert len(batch.results) == 1
        assert len(batch.errors) == 1
        assert batch.errors[0][0] == "1002"

    async def test_index_rebuilt_once(self, tmp_path: Path) -> None:
        """When batch downloads complete, then root index is rebuilt exactly once."""
        config = _config(tmp_path)
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        detail = _detail(volumes=vols)
        client = _mock_client(urls=["https://cdn/a"] * 4)

        with patch("kmoe.download.update_root_index") as mock_rebuild:
            await download_volumes(client, config, detail, ["1001", "1002"], DownloadFormat.EPUB)
            assert mock_rebuild.call_count == 1
