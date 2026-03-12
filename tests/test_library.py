"""Tests for kmoe.library module."""

from __future__ import annotations

import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kmoe.library import (
    ScannedFile,
    detect_title_from_directory,
    find_missing_vol_ids,
    is_scan_only_entry,
    list_archive_contents,
    refresh_entry_from_detail,
    rescan_download_entry,
    rescan_scan_entry,
    scan_book_files,
    scan_untracked_directory,
)
from kmoe.models import (
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
# find_missing_vol_ids
# ---------------------------------------------------------------------------


class TestFindMissingVolIds:
    def test_returns_missing(self) -> None:
        """Vol_ids present remotely but not downloaded are returned."""
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        entry = _entry(downloaded=[_downloaded_vol("1001", "Vol 01")])
        assert find_missing_vol_ids(entry, _detail(volumes=vols)) == ["1002"]

    def test_all_downloaded(self) -> None:
        """When every remote volume is downloaded, returns empty list."""
        vols = [_volume("1001", "Vol 01")]
        entry = _entry(downloaded=[_downloaded_vol("1001", "Vol 01")])
        assert find_missing_vol_ids(entry, _detail(volumes=vols)) == []

    def test_none_downloaded(self) -> None:
        """When nothing is downloaded, returns all remote vol_ids."""
        vols = [_volume("1001", "Vol 01"), _volume("1002", "Vol 02")]
        entry = _entry()
        assert find_missing_vol_ids(entry, _detail(volumes=vols)) == ["1001", "1002"]


# ---------------------------------------------------------------------------
# detect_title_from_directory
# ---------------------------------------------------------------------------


class TestDetectTitleFromDirectory:
    def test_title_id_pattern(self, tmp_path: Path) -> None:
        """Given a directory named '{title}_{id}',
        then the title portion is extracted."""
        d = tmp_path / "夏日時光_55387"
        d.mkdir()
        assert detect_title_from_directory(d) == "夏日時光"

    def test_hex_comic_id_pattern(self, tmp_path: Path) -> None:
        """Given a directory named '{title}_{hex_id}',
        then the title is extracted."""
        d = tmp_path / "SAKAMOTO DAYS_425daf"
        d.mkdir()
        assert detect_title_from_directory(d) == "SAKAMOTO DAYS"

    def test_kmoe_prefix_pattern(self, tmp_path: Path) -> None:
        """Given a directory named '[Kmoe]{title}',
        then the title is extracted."""
        d = tmp_path / "[Kmoe]棋魂"
        d.mkdir()
        assert detect_title_from_directory(d) == "棋魂"

    def test_mox_prefix_pattern(self, tmp_path: Path) -> None:
        """Given a directory named '[Mox]{title}',
        then the title is extracted."""
        d = tmp_path / "[Mox]蠟筆小新"
        d.mkdir()
        assert detect_title_from_directory(d) == "蠟筆小新"

    def test_extract_from_loose_files(self, tmp_path: Path) -> None:
        """Given a plain-named directory containing [Kmoe] files,
        then the comic title is extracted from filenames."""
        d = tmp_path / "my_comics"
        d.mkdir()
        (d / "[Kmoe][進擊的巨人]卷 01.epub").write_bytes(b"x")
        assert detect_title_from_directory(d) == "進擊的巨人"

    def test_returns_none_for_empty_dir(self, tmp_path: Path) -> None:
        """Given an empty directory with no recognizable pattern,
        then None is returned."""
        d = tmp_path / "random"
        d.mkdir()
        assert detect_title_from_directory(d) is None


# ---------------------------------------------------------------------------
# LibraryEntry defaults
# ---------------------------------------------------------------------------


class TestLibraryEntryDefaults:
    def test_scan_only_entry_minimal_fields(self) -> None:
        """LibraryEntry can be created with only a title for scan-only entries."""
        entry = LibraryEntry(title="Test")
        assert entry.book_id == ""
        assert entry.comic_id == ""
        assert entry.meta is None
        assert entry.is_complete is None

    def test_download_entry_still_works(self) -> None:
        """Existing download-style LibraryEntry creation still works."""
        meta = ComicMeta(book_id="123", title="Test")
        entry = LibraryEntry(book_id="123", title="Test", meta=meta, is_complete=False)
        assert entry.book_id == "123"
        assert entry.meta is not None
        assert entry.is_complete is False


# ---------------------------------------------------------------------------
# is_scan_only_entry
# ---------------------------------------------------------------------------


class TestIsScanOnlyEntry:
    def test_scan_only_when_ids_empty(self) -> None:
        entry = LibraryEntry(title="Test")
        assert is_scan_only_entry(entry) is True

    def test_not_scan_only_with_book_id(self) -> None:
        entry = LibraryEntry(title="Test", book_id="123", meta=_meta())
        assert is_scan_only_entry(entry) is False

    def test_not_scan_only_with_comic_id(self) -> None:
        entry = LibraryEntry(title="Test", comic_id="abc", meta=_meta())
        assert is_scan_only_entry(entry) is False


# ---------------------------------------------------------------------------
# scan_untracked_directory
# ---------------------------------------------------------------------------


class TestScanUntrackedDirectory:
    def test_creates_entry_from_epub_files(self, tmp_path: Path) -> None:
        d = tmp_path / "my_manga"
        d.mkdir()
        (d / "[Kmoe][Test Comic]Vol 01.epub").write_bytes(b"x" * 100)
        (d / "[Kmoe][Test Comic]Vol 02.epub").write_bytes(b"y" * 200)
        entry = scan_untracked_directory(d)
        assert entry.title == "Test Comic"
        assert entry.book_id == ""
        assert entry.comic_id == ""
        assert entry.meta is None
        assert entry.is_complete is None
        assert len(entry.downloaded_volumes) == 2
        assert all(v.source == "scan" for v in entry.downloaded_volumes)
        assert all(v.vol_id == "" for v in entry.downloaded_volumes)
        assert (d / "library.json").exists()

    def test_handles_archive_files(self, tmp_path: Path) -> None:
        d = tmp_path / "manga_archive"
        d.mkdir()
        archive = d / "batch.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("[Kmoe][Test]Vol 01.epub", "x" * 50)
        entry = scan_untracked_directory(d)
        assert len(entry.downloaded_volumes) == 1
        assert "batch.zip/" in entry.downloaded_volumes[0].filename

    def test_fallback_title_from_dirname(self, tmp_path: Path) -> None:
        d = tmp_path / "夏日時光_55387"
        d.mkdir()
        (d / "random.epub").write_bytes(b"x" * 100)
        entry = scan_untracked_directory(d)
        assert entry.title == "夏日時光"


# ---------------------------------------------------------------------------
# rescan_scan_entry
# ---------------------------------------------------------------------------


class TestRescanScanEntry:
    def test_picks_up_new_file(self, tmp_path: Path) -> None:
        d = tmp_path / "manga"
        d.mkdir()
        (d / "Vol 01.epub").write_bytes(b"x" * 100)
        entry = scan_untracked_directory(d)
        assert len(entry.downloaded_volumes) == 1
        (d / "Vol 02.epub").write_bytes(b"y" * 200)
        updated = rescan_scan_entry(d, entry)
        assert len(updated.downloaded_volumes) == 2

    def test_drops_removed_file(self, tmp_path: Path) -> None:
        d = tmp_path / "manga"
        d.mkdir()
        (d / "Vol 01.epub").write_bytes(b"x" * 100)
        (d / "Vol 02.epub").write_bytes(b"y" * 200)
        entry = scan_untracked_directory(d)
        assert len(entry.downloaded_volumes) == 2
        (d / "Vol 01.epub").unlink()
        updated = rescan_scan_entry(d, entry)
        assert len(updated.downloaded_volumes) == 1


# ---------------------------------------------------------------------------
# rescan_download_entry
# ---------------------------------------------------------------------------


class TestRescanDownloadEntry:
    def test_keeps_valid_download_record(self, tmp_path: Path) -> None:
        d = tmp_path / "Test_abc123"
        d.mkdir()
        (d / "[Kmoe][Test]Vol 01.epub").write_bytes(b"x" * 1000)
        entry = LibraryEntry(
            book_id="123", comic_id="abc123", title="Test",
            meta=ComicMeta(book_id="123", title="Test"),
            downloaded_volumes=[DownloadedVolume(
                vol_id="1001", title="Vol 01", format="epub",
                filename="[Kmoe][Test]Vol 01.epub",
                downloaded_at=datetime.now(timezone.utc),
                size_bytes=1000, source="download",
            )],
        )
        updated = rescan_download_entry(d, entry)
        assert len(updated.downloaded_volumes) == 1
        assert updated.downloaded_volumes[0].source == "download"

    def test_removes_missing_file(self, tmp_path: Path) -> None:
        d = tmp_path / "Test_abc123"
        d.mkdir()
        entry = LibraryEntry(
            book_id="123", comic_id="abc123", title="Test",
            meta=ComicMeta(book_id="123", title="Test"),
            downloaded_volumes=[DownloadedVolume(
                vol_id="1001", title="Vol 01", format="epub",
                filename="[Kmoe][Test]Vol 01.epub",
                downloaded_at=datetime.now(timezone.utc),
                size_bytes=1000, source="download",
            )],
        )
        updated = rescan_download_entry(d, entry)
        assert len(updated.downloaded_volumes) == 0

    def test_removes_undersized_file(self, tmp_path: Path) -> None:
        d = tmp_path / "Test_abc123"
        d.mkdir()
        (d / "[Kmoe][Test]Vol 01.epub").write_bytes(b"x" * 100)
        entry = LibraryEntry(
            book_id="123", comic_id="abc123", title="Test",
            meta=ComicMeta(book_id="123", title="Test"),
            downloaded_volumes=[DownloadedVolume(
                vol_id="1001", title="Vol 01", format="epub",
                filename="[Kmoe][Test]Vol 01.epub",
                downloaded_at=datetime.now(timezone.utc),
                size_bytes=1000, source="download",
            )],
        )
        updated = rescan_download_entry(d, entry)
        assert len(updated.downloaded_volumes) == 0

    def test_adds_new_unrecorded_file(self, tmp_path: Path) -> None:
        d = tmp_path / "Test_abc123"
        d.mkdir()
        (d / "[Kmoe][Test]Vol 01.epub").write_bytes(b"x" * 1000)
        (d / "[Kmoe][Test]Vol 02.epub").write_bytes(b"y" * 2000)
        entry = LibraryEntry(
            book_id="123", comic_id="abc123", title="Test",
            meta=ComicMeta(book_id="123", title="Test"),
            downloaded_volumes=[DownloadedVolume(
                vol_id="1001", title="Vol 01", format="epub",
                filename="[Kmoe][Test]Vol 01.epub",
                downloaded_at=datetime.now(timezone.utc),
                size_bytes=1000, source="download",
            )],
        )
        updated = rescan_download_entry(d, entry)
        assert len(updated.downloaded_volumes) == 2
        sources = {v.filename: v.source for v in updated.downloaded_volumes}
        assert sources["[Kmoe][Test]Vol 01.epub"] == "download"
        assert sources["[Kmoe][Test]Vol 02.epub"] == "scan"
