"""Local library management for the Kmoe manga downloader.

Each comic is stored in its own directory under the configured download_dir,
with a ``library.json`` file that tracks metadata and downloaded volumes.

Directory layout::

    {download_dir}/{sanitized_title}_{book_id}/library.json
"""

from __future__ import annotations

import re
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

from kmoe.models import (
    AppConfig,
    ComicDetail,
    DownloadedVolume,
    LibraryEntry,
)
from kmoe.utils import ensure_dir, sanitize_filename

log: structlog.stdlib.BoundLogger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Scanned file representation
# ---------------------------------------------------------------------------

_BOOK_EXTENSIONS = {".epub", ".mobi"}


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """A file found during directory scanning.

    May represent a loose file on disk or a file inside an archive
    (ZIP/TAR).  When *archive_path* is not ``None`` the file lives
    inside the archive at *disk_path*.
    """

    name: str
    size: int
    disk_path: Path
    archive_path: Path | None = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_comic_dir(config: AppConfig, comic_id: str, title: str) -> Path:
    """Return the directory path for a comic.

    The directory name is ``{sanitized_title}_{comic_id}`` inside
    *config.download_dir*.  The directory is **not** created by this function.

    Args:
        config: Application configuration.
        comic_id: The URL-form comic ID (e.g. "425daf"), used for directory naming.
        title: The comic title.
    """
    safe_title = sanitize_filename(title)
    return config.download_dir / f"{safe_title}_{comic_id}"


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_entry(config: AppConfig, comic_id: str, title: str) -> LibraryEntry | None:
    """Load a :class:`LibraryEntry` from its ``library.json``.

    Args:
        config: Application configuration.
        comic_id: The URL-form comic ID used for directory naming.
        title: The comic title.

    Returns ``None`` when the file does not exist.
    """
    lib_path = get_comic_dir(config, comic_id, title) / "library.json"
    if not lib_path.exists():
        return None
    try:
        raw = lib_path.read_text(encoding="utf-8")
        return LibraryEntry.model_validate_json(raw)
    except Exception:
        log.warning("failed to load library entry", path=str(lib_path))
        return None


def save_entry(config: AppConfig, entry: LibraryEntry) -> None:
    """Persist a :class:`LibraryEntry` to ``library.json``.

    Creates the comic directory if it does not already exist.
    """
    comic_dir = get_comic_dir(config, entry.comic_id or entry.book_id, entry.title)
    ensure_dir(comic_dir)
    lib_path = comic_dir / "library.json"
    lib_path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def is_volume_downloaded(
    config: AppConfig,
    comic_id: str,
    title: str,
    vol_id: str,
    fmt: str,
) -> bool:
    """Check whether a specific volume+format combination has been downloaded."""
    entry = load_entry(config, comic_id, title)
    if entry is None:
        return False
    return any(v.vol_id == vol_id and v.format == fmt for v in entry.downloaded_volumes)


def add_downloaded_volume(
    config: AppConfig,
    entry: LibraryEntry,
    vol: DownloadedVolume,
) -> LibraryEntry:
    """Add *vol* to the entry's downloaded volumes and persist the change.

    Replaces any existing record with the same ``vol_id`` and ``format``
    to avoid duplicates on re-download.

    Returns the updated :class:`LibraryEntry`.
    """
    entry.downloaded_volumes[:] = [
        v
        for v in entry.downloaded_volumes
        if not (v.vol_id == vol.vol_id and v.format == vol.format)
    ]
    entry.downloaded_volumes.append(vol)
    save_entry(config, entry)
    return entry


def refresh_entry_from_detail(entry: LibraryEntry, detail: ComicDetail) -> LibraryEntry:
    """Refresh a library entry's metadata using remote comic detail.

    Updates ``meta``, ``total_volumes``, ``is_complete``, and ``last_checked``
    from the remote *detail*.  Returns a **new** :class:`LibraryEntry` (the
    model is effectively immutable after construction).
    """
    total = len(detail.volumes)
    downloaded_ids = {v.vol_id for v in entry.downloaded_volumes}
    remote_ids = {v.vol_id for v in detail.volumes}
    is_complete = total > 0 and remote_ids <= downloaded_ids

    return LibraryEntry(
        book_id=entry.book_id,
        comic_id=entry.comic_id or detail.meta.comic_id,
        title=detail.meta.title,
        meta=detail.meta,
        downloaded_volumes=entry.downloaded_volumes,
        total_volumes=total,
        last_checked=datetime.now(timezone.utc),
        is_complete=is_complete,
    )


def find_missing_vol_ids(entry: LibraryEntry, detail: ComicDetail) -> list[str]:
    """Return vol_ids from remote that have no download record.

    Disk validation (file existence, size) is ``scan``'s job.
    This function only compares vol_id sets so that ``update`` stays fast.
    """
    downloaded_ids = {v.vol_id for v in entry.downloaded_volumes}
    return [v.vol_id for v in detail.volumes if v.vol_id not in downloaded_ids]


# ---------------------------------------------------------------------------
# Library scanning
# ---------------------------------------------------------------------------


def list_library(config: AppConfig) -> list[LibraryEntry]:
    """Scan the download directory and return all valid library entries.

    Directories that do not contain a ``library.json`` or whose file cannot be
    parsed are silently skipped.
    """
    entries: list[LibraryEntry] = []
    dl_dir = config.download_dir

    if not dl_dir.exists():
        return entries

    for child in sorted(dl_dir.iterdir()):
        if not child.is_dir():
            continue
        lib_path = child / "library.json"
        if not lib_path.exists():
            continue
        try:
            raw = lib_path.read_text(encoding="utf-8")
            entries.append(LibraryEntry.model_validate_json(raw))
        except Exception:
            log.warning("skipping corrupt library entry", path=str(lib_path))

    return entries


# ---------------------------------------------------------------------------
# File title extraction
# ---------------------------------------------------------------------------

# Matches filenames like "[Mox][棋魂]卷01.kepub.epub" or "[Kmoe][蠟筆小新]卷 01.epub"
_TITLE_PATTERN = re.compile(
    r"^\[(?:Mox|Kmoe)\]\[([^\]]+)\](.+?)(?:\.kepub)?\.(?:epub|mobi|zip|tar(?:\.gz)?|tgz)$"
)


def extract_title_from_filename(filename: str) -> tuple[str, str] | None:
    """Extract comic title and volume title from a Kmoe/Mox filename.

    Returns (comic_title, volume_title) or None if the pattern doesn't match.
    """
    m = _TITLE_PATTERN.match(filename)
    if not m:
        return None
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Directory import
# ---------------------------------------------------------------------------


_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".tgz"}


def _decode_zip_filename(info: zipfile.ZipInfo) -> str:
    """Decode a ZIP entry filename, handling non-UTF-8 archives.

    Many ZIP tools (especially on macOS/Windows with CJK filenames) store
    UTF-8 bytes but don't set the UTF-8 flag (bit 11).  Python's zipfile
    then decodes the bytes as CP437, producing mojibake.  This function
    detects that case and re-decodes as UTF-8.
    """
    name = info.filename
    if info.flag_bits & 0x800:
        # UTF-8 flag is set — Python already decoded correctly
        return name
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return name


def list_archive_contents(archive: Path) -> list[ScannedFile]:
    """List epub/mobi files inside a ZIP or TAR archive without extracting."""
    results: list[ScannedFile] = []
    suffix = archive.suffix.lower()
    name_lower = archive.name.lower()

    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    fname = Path(_decode_zip_filename(info)).name
                    if fname.startswith("._"):
                        continue
                    if Path(fname).suffix.lower() in _BOOK_EXTENSIONS:
                        results.append(
                            ScannedFile(
                                name=fname,
                                size=info.file_size,
                                disk_path=archive,
                                archive_path=archive,
                            )
                        )
        elif suffix in {".tar", ".tgz"} or name_lower.endswith(".tar.gz"):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    fname = Path(member.name).name
                    if fname.startswith("._"):
                        continue
                    if Path(fname).suffix.lower() in _BOOK_EXTENSIONS:
                        results.append(
                            ScannedFile(
                                name=fname,
                                size=member.size,
                                disk_path=archive,
                                archive_path=archive,
                            )
                        )
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
        log.warning("failed to read archive", path=str(archive), error=str(exc))

    return results


def scan_book_files(directory: Path) -> list[ScannedFile]:
    """Return all epub/mobi files in a directory, including inside archives."""
    files: list[ScannedFile] = []
    for f in sorted(directory.iterdir()):
        if not f.is_file() or f.name.startswith("._"):
            continue
        suffix = f.suffix.lower()
        name_lower = f.name.lower()
        if suffix in _BOOK_EXTENSIONS:
            files.append(ScannedFile(name=f.name, size=f.stat().st_size, disk_path=f))
        elif suffix in _ARCHIVE_EXTENSIONS or name_lower.endswith(".tar.gz"):
            files.extend(list_archive_contents(f))
    return files


def detect_title_from_directory(directory: Path) -> str | None:
    """Detect the comic title from directory name or files.

    Tries in order:
    1. Directory name pattern ``{title}_{id}``
    2. Directory name pattern ``[Kmoe][title]`` / ``[Mox][title]``
    3. Loose files matching ``[Kmoe][title]vol.ext``
    4. Files inside ZIP/TAR archives matching the same pattern
    5. Bare directory name as fallback (if the directory contains any book files)
    """
    dir_name = directory.name

    # Pattern 1: {title}_{id} (result of previous scan or download)
    # The ID can be numeric (book_id like "34854") or hex-like (comic_id like "425daf")
    if "_" in dir_name:
        parts = dir_name.rsplit("_", 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]+", parts[1]):
            title = parts[0]
            if title:
                return title

    # Pattern 2: [Kmoe] or [Mox] prefix
    if dir_name.startswith("[Kmoe]") or dir_name.startswith("[Mox]"):
        title = dir_name
        title = re.sub(r"^\[(?:Kmoe|Mox)\]", "", title)
        if title:
            return title

    # Pattern 3: extract from loose file names
    for f in directory.iterdir():
        if not f.is_file():
            continue
        info = extract_title_from_filename(f.name)
        if info is not None:
            return info[0]

    # Pattern 4: extract from files inside archives
    scanned = scan_book_files(directory)
    for sf in scanned:
        info = extract_title_from_filename(sf.name)
        if info is not None:
            return info[0]

    # Fallback: use directory name if it contains any book files
    if scanned:
        return dir_name

    return None


# ---------------------------------------------------------------------------
# Scan-only helpers
# ---------------------------------------------------------------------------


def is_scan_only_entry(entry: LibraryEntry) -> bool:
    """Return True when the entry has no online IDs (local-only)."""
    return not entry.comic_id and not entry.book_id


def _build_scan_volumes(files: list[ScannedFile]) -> list[DownloadedVolume]:
    """Convert scanned files into download records with ``source="scan"``."""
    volumes: list[DownloadedVolume] = []
    for sf in files:
        info = extract_title_from_filename(sf.name)
        title = info[1] if info else Path(sf.name).stem
        suffix = Path(sf.name).suffix.lower()
        fmt = "mobi" if suffix == ".mobi" else "epub"
        filename = f"{sf.archive_path.name}/{sf.name}" if sf.archive_path else sf.name
        volumes.append(
            DownloadedVolume(
                vol_id="",
                title=title,
                format=fmt,
                filename=filename,
                downloaded_at=datetime.fromtimestamp(sf.disk_path.stat().st_mtime, tz=timezone.utc),
                size_bytes=sf.size,
                source="scan",
            )
        )
    return volumes


def scan_untracked_directory(dir_path: Path) -> LibraryEntry:
    """Create a library entry for a directory with no ``library.json``.

    Scans disk files and writes ``library.json`` directly to *dir_path*.
    Does **not** rename the directory or contact the remote server.
    The caller must ensure ``detect_title_from_directory`` returns non-None.
    """
    files = scan_book_files(dir_path)
    title = detect_title_from_directory(dir_path)
    assert title is not None  # caller guarantees
    downloaded = _build_scan_volumes(files)
    entry = LibraryEntry(
        title=title,
        downloaded_volumes=downloaded,
        total_volumes=len(downloaded),
        last_checked=datetime.now(timezone.utc),
    )
    (dir_path / "library.json").write_text(entry.model_dump_json(indent=2), encoding="utf-8")
    return entry


def rescan_scan_entry(dir_path: Path, entry: LibraryEntry) -> LibraryEntry:
    """Re-scan a scan-only directory and rebuild its library entry.

    Preserves the existing title; rebuilds downloaded_volumes from disk.
    """
    files = scan_book_files(dir_path)
    downloaded = _build_scan_volumes(files)
    updated = LibraryEntry(
        book_id=entry.book_id,
        comic_id=entry.comic_id,
        title=entry.title,
        meta=entry.meta,
        downloaded_volumes=downloaded,
        total_volumes=len(downloaded),
        last_checked=datetime.now(timezone.utc),
        is_complete=entry.is_complete,
    )
    (dir_path / "library.json").write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    return updated


def rescan_download_entry(dir_path: Path, entry: LibraryEntry) -> LibraryEntry:
    """Re-scan a download-tracked directory and reconcile with disk.

    For ``source="download"`` records: keeps only if the file exists on disk
    and is at least 80% of the recorded size.  For ``source="scan"`` records:
    keeps only if the file exists.  New unrecorded files are added with
    ``source="scan"``.
    """
    files = scan_book_files(dir_path)

    # Build filename -> ScannedFile lookup
    disk_lookup: dict[str, ScannedFile] = {}
    for sf in files:
        key = f"{sf.archive_path.name}/{sf.name}" if sf.archive_path else sf.name
        disk_lookup[key] = sf

    # Reconcile existing records
    kept: list[DownloadedVolume] = []
    matched_filenames: set[str] = set()
    for dv in entry.downloaded_volumes:
        sf = disk_lookup.get(dv.filename)
        if sf is None:
            continue
        matched_filenames.add(dv.filename)
        if dv.source == "download" and sf.size < 0.8 * dv.size_bytes:
            continue
        kept.append(dv)

    # Add new unrecorded files
    for filename, sf in disk_lookup.items():
        if filename in matched_filenames:
            continue
        info = extract_title_from_filename(sf.name)
        title = info[1] if info else Path(sf.name).stem
        suffix = Path(sf.name).suffix.lower()
        fmt = "mobi" if suffix == ".mobi" else "epub"
        kept.append(
            DownloadedVolume(
                vol_id="",
                title=title,
                format=fmt,
                filename=filename,
                downloaded_at=datetime.fromtimestamp(sf.disk_path.stat().st_mtime, tz=timezone.utc),
                size_bytes=sf.size,
                source="scan",
            )
        )

    updated = LibraryEntry(
        book_id=entry.book_id,
        comic_id=entry.comic_id,
        title=entry.title,
        meta=entry.meta,
        downloaded_volumes=kept,
        total_volumes=len(kept),
        last_checked=datetime.now(timezone.utc),
        is_complete=entry.is_complete,
    )
    (dir_path / "library.json").write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    return updated
