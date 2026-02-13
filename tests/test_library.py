"""Tests for kmoe.library module."""

from __future__ import annotations

import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kmoe.library import (
    ScannedFile,
    find_stale_volumes,
    get_comic_dir,
    list_archive_contents,
    match_files_to_volumes,
    refresh_entry_from_detail,
    scan_book_files,
)
from kmoe.models import (
    AppConfig,
    ComicDetail,
    ComicMeta,
    DownloadedVolume,
    LibraryEntry,
    Volume,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(book_id: str = "18488", comic_id: str = "abc123") -> ComicMeta:
    return ComicMeta(book_id=book_id, comic_id=comic_id, title="Test Comic")


def _volume(vol_id: str = "1001", title: str = "Vol 01") -> Volume:
    return Volume(vol_id=vol_id, title=title)


def _detail(volumes: list[Volume] | None = None, **kw: str) -> ComicDetail:
    return ComicDetail(meta=_meta(**kw), volumes=[_volume()] if volumes is None else volumes)


def _downloaded_vol(vol_id: str = "1001", title: str = "Vol 01") -> DownloadedVolume:
    return DownloadedVolume(
        vol_id=vol_id,
        title=title,
        format="epub",
        filename=f"[Kmoe][Test Comic]{title}.epub",
        downloaded_at=datetime.now(timezone.utc),
        size_bytes=1024,
    )


def _entry(
    downloaded: list[DownloadedVolume] | None = None,
    total_volumes: int = 0,
) -> LibraryEntry:
    return LibraryEntry(
        book_id="18488",
        comic_id="abc123",
        title="Test Comic",
        meta=_meta(),
        downloaded_volumes=downloaded or [],
        total_volumes=total_volumes,
    )


# ---------------------------------------------------------------------------
# refresh_entry_from_detail
# ---------------------------------------------------------------------------


class TestRefreshEntryFromDetail:
    def test_updates_total_volumes(self) -> None:
        """Given a detail with 3 volumes, total_volumes is set to 3."""
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02"), _volume("1003", "Vol 03")]
        entry = _entry()
        result = refresh_entry_from_detail(entry, _detail(volumes=vols))
        assert result.total_volumes == 3

    def test_is_complete_when_all_downloaded(self) -> None:
        """Given all remote volumes are downloaded, is_complete is True."""
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        downloaded = [_downloaded_vol("1001", "Vol 01"), _downloaded_vol("1002", "Vol 02")]
        entry = _entry(downloaded=downloaded)
        result = refresh_entry_from_detail(entry, _detail(volumes=vols))
        assert result.is_complete is True
        assert result.total_volumes == 2

    def test_not_complete_when_missing_volumes(self) -> None:
        """Given some remote volumes are not downloaded, is_complete is False."""
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        downloaded = [_downloaded_vol("1001", "Vol 01")]
        entry = _entry(downloaded=downloaded)
        result = refresh_entry_from_detail(entry, _detail(volumes=vols))
        assert result.is_complete is False

    def test_not_complete_when_no_remote_volumes(self) -> None:
        """Given zero remote volumes, is_complete is False."""
        entry = _entry()
        result = refresh_entry_from_detail(entry, _detail(volumes=[]))
        assert result.is_complete is False
        assert result.total_volumes == 0

    def test_preserves_downloaded_volumes(self) -> None:
        """Downloaded volumes list is preserved."""
        downloaded = [_downloaded_vol("1001", "Vol 01")]
        entry = _entry(downloaded=downloaded)
        result = refresh_entry_from_detail(entry, _detail())
        assert len(result.downloaded_volumes) == 1
        assert result.downloaded_volumes[0].vol_id == "1001"

    def test_updates_meta(self) -> None:
        """Meta is updated from detail."""
        meta = ComicMeta(book_id="18488", comic_id="abc123", title="New Title")
        detail = ComicDetail(meta=meta, volumes=[_volume()])
        entry = _entry()
        result = refresh_entry_from_detail(entry, detail)
        assert result.title == "New Title"

    def test_fills_comic_id_from_detail(self) -> None:
        """When entry has no comic_id, it's filled from detail."""
        entry = LibraryEntry(
            book_id="18488", comic_id="", title="Test Comic", meta=_meta(comic_id="")
        )
        detail = _detail(comic_id="abc123")
        result = refresh_entry_from_detail(entry, detail)
        assert result.comic_id == "abc123"


# ---------------------------------------------------------------------------
# list_archive_contents
# ---------------------------------------------------------------------------


class TestListArchiveContents:
    def test_zip_with_epub_files(self, tmp_path: Path) -> None:
        """ZIP containing epub files returns ScannedFile entries."""
        archive = tmp_path / "comics.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Vol 01.epub", "fake epub data")
            zf.writestr("Vol 02.mobi", "fake mobi data")
            zf.writestr("readme.txt", "not a book")

        result = list_archive_contents(archive)
        names = {sf.name for sf in result}
        assert names == {"Vol 01.epub", "Vol 02.mobi"}
        assert all(sf.archive_path == archive for sf in result)
        assert all(sf.disk_path == archive for sf in result)

    def test_tar_with_epub_files(self, tmp_path: Path) -> None:
        """TAR containing epub files returns ScannedFile entries."""
        # Create some temp files to add to the tar
        epub_file = tmp_path / "Vol 01.epub"
        epub_file.write_bytes(b"fake epub data")

        archive = tmp_path / "comics.tar"
        with tarfile.open(archive, "w") as tf:
            tf.add(epub_file, arcname="Vol 01.epub")

        result = list_archive_contents(archive)
        assert len(result) == 1
        assert result[0].name == "Vol 01.epub"

    def test_tgz_with_epub_files(self, tmp_path: Path) -> None:
        """TGZ containing epub files returns ScannedFile entries."""
        epub_file = tmp_path / "Vol 01.epub"
        epub_file.write_bytes(b"fake epub data")

        archive = tmp_path / "comics.tgz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(epub_file, arcname="Vol 01.epub")

        result = list_archive_contents(archive)
        assert len(result) == 1
        assert result[0].name == "Vol 01.epub"

    def test_zip_with_no_book_files(self, tmp_path: Path) -> None:
        """ZIP with no epub/mobi files returns empty list."""
        archive = tmp_path / "misc.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("readme.txt", "just text")

        result = list_archive_contents(archive)
        assert result == []

    def test_corrupt_zip_returns_empty(self, tmp_path: Path) -> None:
        """Corrupt archive returns empty list without raising."""
        archive = tmp_path / "bad.zip"
        archive.write_bytes(b"not a zip")
        result = list_archive_contents(archive)
        assert result == []

    def test_nested_paths_in_zip(self, tmp_path: Path) -> None:
        """Files in subdirectories inside ZIP use only the filename."""
        archive = tmp_path / "nested.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("subdir/deep/Vol 03.epub", "data")

        result = list_archive_contents(archive)
        assert len(result) == 1
        assert result[0].name == "Vol 03.epub"


# ---------------------------------------------------------------------------
# scan_book_files
# ---------------------------------------------------------------------------


class TestScanBookFiles:
    def test_loose_files(self, tmp_path: Path) -> None:
        """Loose epub/mobi files are returned as ScannedFile."""
        (tmp_path / "Vol 01.epub").write_bytes(b"x" * 100)
        (tmp_path / "Vol 02.mobi").write_bytes(b"y" * 200)
        (tmp_path / "readme.txt").write_bytes(b"text")

        result = scan_book_files(tmp_path)
        names = {sf.name for sf in result}
        assert names == {"Vol 01.epub", "Vol 02.mobi"}
        assert all(sf.archive_path is None for sf in result)

    def test_files_inside_zip(self, tmp_path: Path) -> None:
        """Files inside a ZIP archive are included."""
        archive = tmp_path / "batch.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Vol 01.epub", "data1")
            zf.writestr("Vol 02.epub", "data2")

        result = scan_book_files(tmp_path)
        assert len(result) == 2
        assert all(sf.archive_path is not None for sf in result)

    def test_mixed_loose_and_archive(self, tmp_path: Path) -> None:
        """Mix of loose files and archive contents."""
        (tmp_path / "Vol 01.epub").write_bytes(b"x" * 100)
        archive = tmp_path / "more.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Vol 02.epub", "data")

        result = scan_book_files(tmp_path)
        names = {sf.name for sf in result}
        assert names == {"Vol 01.epub", "Vol 02.epub"}


# ---------------------------------------------------------------------------
# match_files_to_volumes (with ScannedFile)
# ---------------------------------------------------------------------------


class TestMatchFilesToVolumes:
    def test_exact_match(self) -> None:
        """ScannedFiles with matching vol titles are matched."""
        files = [
            ScannedFile(name="[Kmoe][Test Comic]Vol 01.epub", size=100, disk_path=Path("/a")),
            ScannedFile(name="[Kmoe][Test Comic]Vol 02.epub", size=200, disk_path=Path("/b")),
        ]
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        result = match_files_to_volumes(files, vols)
        assert len(result.matched) == 2
        assert len(result.unmatched) == 0

    def test_unmatched_files(self) -> None:
        """Files that don't match any volume end up in unmatched."""
        files = [
            ScannedFile(name="random_file.epub", size=100, disk_path=Path("/a")),
        ]
        vols = [_volume("1001", "Vol 01")]
        result = match_files_to_volumes(files, vols)
        assert len(result.matched) == 0
        assert len(result.unmatched) == 1

    def test_archive_scanned_file(self) -> None:
        """ScannedFiles from archives match correctly."""
        files = [
            ScannedFile(
                name="[Kmoe][Test Comic]Vol 01.epub",
                size=100,
                disk_path=Path("/archive.zip"),
                archive_path=Path("/archive.zip"),
            ),
        ]
        vols = [_volume("1001", "Vol 01")]
        result = match_files_to_volumes(files, vols)
        assert len(result.matched) == 1
        assert result.matched[0][0].archive_path is not None


# ---------------------------------------------------------------------------
# find_stale_volumes
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(download_dir=tmp_path)


class TestFindStaleVolumes:
    def test_missing_volume(self, tmp_path: Path) -> None:
        """Volume not in downloaded_volumes is returned as stale."""
        config = _config(tmp_path)
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        entry = _entry(downloaded=[_downloaded_vol("1001", "Vol 01")])
        detail = _detail(volumes=vols)

        # Create the directory and file for vol 1001 so it's not stale
        comic_dir = get_comic_dir(config, "abc123", "Test Comic")
        comic_dir.mkdir(parents=True)
        (comic_dir / "[Kmoe][Test Comic]Vol 01.epub").write_bytes(b"x" * 1024)

        result = find_stale_volumes(config, entry, detail)
        assert "1002" in result
        assert "1001" not in result

    def test_file_missing_on_disk(self, tmp_path: Path) -> None:
        """Volume recorded but file missing on disk is stale."""
        config = _config(tmp_path)
        entry = _entry(downloaded=[_downloaded_vol("1001", "Vol 01")])
        detail = _detail(volumes=[_volume("1001", "Vol 01")])

        # Don't create the file
        comic_dir = get_comic_dir(config, "abc123", "Test Comic")
        comic_dir.mkdir(parents=True)

        result = find_stale_volumes(config, entry, detail)
        assert "1001" in result

    def test_corrupt_file_too_small(self, tmp_path: Path) -> None:
        """Volume with file much smaller than expected is stale."""
        config = _config(tmp_path)
        vol = Volume(vol_id="1001", title="Vol 01", size_epub_mb=100.0)
        entry = _entry(downloaded=[_downloaded_vol("1001", "Vol 01")])
        detail = _detail(volumes=[vol])

        comic_dir = get_comic_dir(config, "abc123", "Test Comic")
        comic_dir.mkdir(parents=True)
        # Write only 7KB vs expected 100MB
        (comic_dir / "[Kmoe][Test Comic]Vol 01.epub").write_bytes(b"x" * 7000)

        result = find_stale_volumes(config, entry, detail)
        assert "1001" in result

    def test_healthy_file_not_stale(self, tmp_path: Path) -> None:
        """Volume with file close to expected size is not stale."""
        config = _config(tmp_path)
        vol = Volume(vol_id="1001", title="Vol 01", size_epub_mb=0.001)
        entry = _entry(downloaded=[_downloaded_vol("1001", "Vol 01")])
        detail = _detail(volumes=[vol])

        comic_dir = get_comic_dir(config, "abc123", "Test Comic")
        comic_dir.mkdir(parents=True)
        (comic_dir / "[Kmoe][Test Comic]Vol 01.epub").write_bytes(b"x" * 1024)

        result = find_stale_volumes(config, entry, detail)
        assert result == []

    def test_no_expected_size_not_stale(self, tmp_path: Path) -> None:
        """Volume with no expected size and file exists is not stale."""
        config = _config(tmp_path)
        entry = _entry(downloaded=[_downloaded_vol("1001", "Vol 01")])
        detail = _detail(volumes=[_volume("1001", "Vol 01")])  # size_epub_mb=0

        comic_dir = get_comic_dir(config, "abc123", "Test Comic")
        comic_dir.mkdir(parents=True)
        (comic_dir / "[Kmoe][Test Comic]Vol 01.epub").write_bytes(b"x" * 100)

        result = find_stale_volumes(config, entry, detail)
        assert result == []
