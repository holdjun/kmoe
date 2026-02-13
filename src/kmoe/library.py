"""Local library management for the Kmoe manga downloader.

Each comic is stored in its own directory under the configured download_dir,
with a ``library.json`` file that tracks metadata and downloaded volumes.

Directory layout::

    {download_dir}/library.json                       # root index
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
    LibraryIndex,
    LibraryIndexEntry,
    Volume,
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
# Root index
# ---------------------------------------------------------------------------


def _index_path(config: AppConfig) -> Path:
    return config.download_dir / "library.json"


def load_index(config: AppConfig) -> LibraryIndex | None:
    """Load the root library index."""
    path = _index_path(config)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return LibraryIndex.model_validate_json(raw)
    except Exception:
        log.warning("failed to load library index", path=str(path))
        return None


def save_index(config: AppConfig, entries: list[LibraryEntry]) -> None:
    """Build and persist the root library index from per-comic entries."""
    comics: list[LibraryIndexEntry] = []
    for entry in entries:
        comic_dir = get_comic_dir(config, entry.comic_id or entry.book_id, entry.title)
        comics.append(
            LibraryIndexEntry(
                book_id=entry.book_id,
                title=entry.title,
                dir_name=comic_dir.name,
                authors=entry.meta.authors,
                status=entry.meta.status,
                total_volumes=entry.total_volumes,
                downloaded_volumes=len(entry.downloaded_volumes),
                is_complete=entry.is_complete,
            )
        )

    index = LibraryIndex(updated_at=datetime.now(timezone.utc), comics=comics)
    ensure_dir(config.download_dir)
    _index_path(config).write_text(index.model_dump_json(indent=2), encoding="utf-8")


def rebuild_index(config: AppConfig) -> LibraryIndex:
    """Scan all subdirectory library.json files and rebuild the root index."""
    entries = list_library(config)
    save_index(config, entries)
    return load_index(config) or LibraryIndex(updated_at=datetime.now(timezone.utc))


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


def save_entry(config: AppConfig, entry: LibraryEntry, *, update_index: bool = True) -> None:
    """Persist a :class:`LibraryEntry` to ``library.json``.

    Creates the comic directory if it does not already exist.

    Args:
        config: Application configuration.
        entry: The library entry to save.
        update_index: Whether to trigger a root index rebuild. Set to ``False``
            during batch operations and call :func:`update_root_index` once at the end.
    """
    comic_dir = get_comic_dir(config, entry.comic_id or entry.book_id, entry.title)
    ensure_dir(comic_dir)
    lib_path = comic_dir / "library.json"
    lib_path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")

    if update_index:
        update_root_index(config)


def update_root_index(config: AppConfig) -> None:
    """Re-scan subdirectories and update the root index."""
    try:
        entries = list_library(config)
        save_index(config, entries)
    except Exception:
        log.warning("failed to update root index")


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
    *,
    update_index: bool = True,
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
    save_entry(config, entry, update_index=update_index)
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


def find_stale_volumes(
    config: AppConfig,
    entry: LibraryEntry,
    detail: ComicDetail,
) -> list[str]:
    """Return vol_ids that are missing or have corrupt files on disk.

    A volume is considered stale when:
    - It exists remotely but has no download record, **or**
    - It is recorded but the file on disk is missing, **or**
    - It is recorded but the file size is far below the expected size
      (less than half the expected size when the expected size is known).
    """
    comic_id = entry.comic_id or entry.book_id
    comic_dir = get_comic_dir(config, comic_id, entry.title)

    downloaded_map: dict[str, DownloadedVolume] = {dv.vol_id: dv for dv in entry.downloaded_volumes}
    remote_vols: dict[str, Volume] = {v.vol_id: v for v in detail.volumes}

    stale: list[str] = []
    for vid, vol in remote_vols.items():
        dv = downloaded_map.get(vid)
        if dv is None:
            # Never downloaded
            stale.append(vid)
            continue

        # Check file exists on disk
        fpath = comic_dir / dv.filename
        if not fpath.exists():
            stale.append(vid)
            continue

        # Check file size sanity
        actual_bytes = fpath.stat().st_size
        expected_mb = vol.size_epub_mb if dv.format == "epub" else vol.size_mobi_mb
        if expected_mb > 0:
            expected_bytes = expected_mb * 1024 * 1024
            if actual_bytes < expected_bytes * 0.5:
                stale.append(vid)

    return stale


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


def _normalize_vol_title(title: str) -> str:
    """Normalize a volume title for fuzzy matching.

    Strips whitespace differences so "卷01" matches "卷 01".
    """
    return re.sub(r"\s+", "", title)


def _extract_vol_title_from_filename(filename: str) -> str | None:
    """Extract volume title from various filename formats.

    Supports:
    - [Kmoe][Title]Vol 01.epub -> Vol 01
    - [Mox][Title]卷 01.epub -> 卷 01
    - Title - Vol 01.epub -> Vol 01
    - Title 卷01.epub -> 卷01
    - Vol 01.epub -> Vol 01
    """
    # Remove extension
    name = re.sub(
        r"(?:\.kepub)?\.(?:epub|mobi|zip|tar(?:\.gz)?|tgz)$", "", filename, flags=re.IGNORECASE
    )

    # Pattern 1: [Kmoe|Mox][Title]VolTitle
    m = re.match(r"^\[(?:Mox|Kmoe)\]\[[^\]]+\](.+)$", name)
    if m:
        return m.group(1)

    # Pattern 2: Title - VolTitle (common separator patterns)
    for sep in [" - ", " _ ", " — "]:
        if sep in name:
            return name.rsplit(sep, 1)[-1]

    # Pattern 3: Just volume number/name patterns at the end
    # e.g. "Some Title 卷01" -> "卷01"
    m = re.search(
        r"((?:卷|第|Vol\.?|Chapter|Ch\.?)\s*\d+(?:\s*\-\s*\d+)?(?:\s*\(.+?\))?)$",
        name,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)

    return None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Result of matching files to volumes."""

    matched: list[tuple[ScannedFile, Volume]]
    unmatched: list[ScannedFile]


def match_files_to_volumes(
    files: list[ScannedFile],
    volumes: list[Volume],
) -> MatchResult:
    """Match local files to remote volume objects.

    Uses multiple strategies for matching:
    1. Exact normalized title match
    2. Fuzzy match (one contains the other after normalization)

    Returns a MatchResult with matched pairs and unmatched files.
    """
    # Build a lookup from normalized volume title -> Volume
    vol_lookup: dict[str, Volume] = {}
    for vol in volumes:
        norm = _normalize_vol_title(vol.title)
        vol_lookup[norm] = vol

    matched: list[tuple[ScannedFile, Volume]] = []
    unmatched: list[ScannedFile] = []
    matched_vol_ids: set[str] = set()

    for sf in files:
        # Try [Kmoe][Title]VolTitle format first
        info = extract_title_from_filename(sf.name)
        if info is not None:
            _comic_title, vol_title = info
            norm = _normalize_vol_title(vol_title)
            if norm in vol_lookup:
                vol = vol_lookup[norm]
                if vol.vol_id not in matched_vol_ids:
                    matched.append((sf, vol))
                    matched_vol_ids.add(vol.vol_id)
                    continue

        # Try broader extraction
        vol_title = _extract_vol_title_from_filename(sf.name)
        if vol_title:
            norm = _normalize_vol_title(vol_title)

            # Exact match
            if norm in vol_lookup:
                vol = vol_lookup[norm]
                if vol.vol_id not in matched_vol_ids:
                    matched.append((sf, vol))
                    matched_vol_ids.add(vol.vol_id)
                    continue

            # Fuzzy match: check if vol_title contains or is contained by volume title
            for vol_norm, vol in vol_lookup.items():
                if vol.vol_id in matched_vol_ids:
                    continue
                if norm in vol_norm or vol_norm in norm:
                    matched.append((sf, vol))
                    matched_vol_ids.add(vol.vol_id)
                    break
            else:
                unmatched.append(sf)
        else:
            unmatched.append(sf)

    return MatchResult(matched=matched, unmatched=unmatched)


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
        if not f.is_file():
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


def import_directory(
    config: AppConfig,
    dir_path: Path,
    comic_id: str,
    detail: ComicDetail,
) -> tuple[LibraryEntry, list[ScannedFile]]:
    """Import an existing directory as a library entry.

    Scans files (including inside ZIP/TAR archives), matches them to remote
    volumes, creates a LibraryEntry, saves library.json, and renames the
    directory to the canonical format.

    Args:
        config: Application configuration.
        dir_path: Path to the directory to import.
        comic_id: The URL-form comic ID (for directory naming).
        detail: Comic detail including meta and volumes.

    Returns the created LibraryEntry and a list of unmatched files.
    """
    meta = detail.meta
    title = meta.title

    # Scan files (including archive contents)
    files = scan_book_files(dir_path)

    # Match to volumes
    match_result = match_files_to_volumes(files, detail.volumes)

    # Build downloaded volumes list
    downloaded: list[DownloadedVolume] = []
    for sf, vol in match_result.matched:
        suffix = Path(sf.name).suffix.lower()
        fmt = "mobi" if suffix == ".mobi" else "epub"

        # For files inside archives, record as "archive.zip/filename"
        filename = f"{sf.archive_path.name}/{sf.name}" if sf.archive_path is not None else sf.name

        downloaded.append(
            DownloadedVolume(
                vol_id=vol.vol_id,
                title=vol.title,
                format=fmt,
                filename=filename,
                downloaded_at=datetime.fromtimestamp(sf.disk_path.stat().st_mtime, tz=timezone.utc),
                size_bytes=sf.size,
            )
        )

    entry = refresh_entry_from_detail(
        LibraryEntry(
            book_id=meta.book_id,
            comic_id=comic_id,
            title=title,
            meta=meta,
            downloaded_volumes=downloaded,
        ),
        detail,
    )

    # Write library.json inside the existing directory first
    lib_path = dir_path / "library.json"
    lib_path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")

    # Rename directory to canonical format if needed
    canonical_dir = get_comic_dir(config, comic_id, title)
    if dir_path != canonical_dir and not canonical_dir.exists():
        dir_path.rename(canonical_dir)
        log.info("renamed directory", old=dir_path.name, new=canonical_dir.name)

    # Update root index
    update_root_index(config)

    return entry, match_result.unmatched
