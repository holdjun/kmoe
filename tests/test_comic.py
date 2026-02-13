"""Tests for kmoe.comic module."""

from __future__ import annotations

import pytest

from kmoe.comic import build_download_url, find_volume
from kmoe.constants import DownloadFormat
from kmoe.exceptions import VolumeNotFoundError
from kmoe.models import ComicDetail, ComicMeta, Volume

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detail(volumes: list[Volume] | None = None) -> ComicDetail:
    meta = ComicMeta(book_id="18488", title="Test Comic")
    return ComicDetail(meta=meta, volumes=volumes or [])


def _volume(vol_id: str = "1001", title: str = "Vol 01", file_count: int = 190) -> Volume:
    return Volume(vol_id=vol_id, title=title, file_count=file_count)


# ---------------------------------------------------------------------------
# build_download_url
# ---------------------------------------------------------------------------


class TestBuildDownloadUrl:
    """Given a domain, book_id, volume, and download format."""

    def test_epub_url_format(self) -> None:
        """When format is EPUB,
        then the URL contains format_code=2."""
        vol = _volume()
        url = build_download_url("kxx.moe", "18488", vol, DownloadFormat.EPUB)
        assert url == "https://kxx.moe/dl/18488/1001/0/2/190/"

    def test_mobi_url_format(self) -> None:
        """When format is MOBI,
        then the URL contains format_code=1."""
        vol = _volume()
        url = build_download_url("kxx.moe", "18488", vol, DownloadFormat.MOBI)
        assert url == "https://kxx.moe/dl/18488/1001/0/1/190/"

    def test_custom_line(self) -> None:
        """When a custom line number is specified,
        then it appears in the URL path."""
        vol = _volume()
        url = build_download_url("kzz.moe", "18488", vol, DownloadFormat.EPUB, line=3)
        assert url == "https://kzz.moe/dl/18488/1001/3/2/190/"


# ---------------------------------------------------------------------------
# find_volume
# ---------------------------------------------------------------------------


class TestFindVolume:
    """Given a ComicDetail with a list of volumes."""

    def test_finds_existing_volume(self) -> None:
        """When the target vol_id exists in the list,
        then the matching Volume is returned."""
        detail = _detail([_volume("1001"), _volume("1002"), _volume("1003")])
        vol = find_volume(detail, "1002")
        assert vol.vol_id == "1002"

    def test_raises_for_missing_volume(self) -> None:
        """When the target vol_id does not exist,
        then VolumeNotFoundError is raised."""
        detail = _detail([_volume("1001")])
        with pytest.raises(VolumeNotFoundError):
            find_volume(detail, "9999")

    def test_raises_for_empty_volumes(self) -> None:
        """When the comic has no volumes,
        then VolumeNotFoundError is raised."""
        detail = _detail([])
        with pytest.raises(VolumeNotFoundError):
            find_volume(detail, "1001")
