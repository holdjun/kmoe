"""Download manager for the Kmoe manga downloader.

Orchestrates downloading one or more volumes using the client, comic,
and library modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from kmoe.comic import find_volume
from kmoe.constants import DownloadFormat
from kmoe.exceptions import DownloadError
from kmoe.library import (
    get_comic_dir,
    load_entry,
    refresh_entry_from_detail,
    save_entry,
)
from kmoe.models import DownloadedVolume, LibraryEntry
from kmoe.utils import sanitize_filename

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from kmoe.client import KmoeClient
    from kmoe.models import AppConfig, ComicDetail, Volume

log: structlog.stdlib.BoundLogger = structlog.get_logger()

# Format name lookup (DownloadFormat enum value -> lowercase extension string)
_FORMAT_NAMES: dict[DownloadFormat, str] = {
    DownloadFormat.MOBI: "mobi",
    DownloadFormat.EPUB: "epub",
}

# Reverse lookup (lowercase string -> DownloadFormat)
_FORMAT_FROM_STR: dict[str, DownloadFormat] = {v: k for k, v in _FORMAT_NAMES.items()}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Result of downloading a single volume."""

    path: Path
    volume: Volume
    skipped: bool
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BatchDownloadResult:
    """Result of downloading multiple volumes."""

    results: list[DownloadResult]
    errors: list[tuple[str, Exception]]


# ---------------------------------------------------------------------------
# Format resolution
# ---------------------------------------------------------------------------


def resolve_format(format_str: str) -> DownloadFormat:
    """Convert a format string to a :class:`DownloadFormat` enum member.

    Args:
        format_str: One of ``"epub"`` or ``"mobi"`` (case-insensitive).

    Returns:
        The corresponding :class:`DownloadFormat`.

    Raises:
        DownloadError: If *format_str* is not a recognised format.
    """
    fmt = _FORMAT_FROM_STR.get(format_str.lower())
    if fmt is None:
        raise DownloadError(
            f"Invalid download format: {format_str!r}. Valid formats: {', '.join(_FORMAT_FROM_STR)}"
        )
    return fmt


# ---------------------------------------------------------------------------
# Multi-line download URL fallback
# ---------------------------------------------------------------------------


async def get_download_urls(
    client: KmoeClient,
    book_id: str,
    vol_id: str,
    fmt: DownloadFormat,
    lines: tuple[int, ...] = (0, 1),
) -> list[str]:
    """Obtain download URLs from multiple server lines.

    Returns a list of CDN URLs (one per successful line). The caller should
    try downloading from each URL in order until one succeeds.

    Raises :class:`DownloadError` if **no** line returns a valid URL.
    """
    urls: list[str] = []
    last_error: Exception | None = None

    for line in lines:
        try:
            url = await client.get_download_url(
                book_id=book_id,
                vol_id=vol_id,
                fmt=int(fmt),
                line=line,
            )
            log.info("download url obtained", vol_id=vol_id, line=line)
            urls.append(url)
        except Exception as exc:
            log.warning(
                "failed to get download url from line",
                vol_id=vol_id,
                line=line,
                error=str(exc),
            )
            last_error = exc

    if not urls:
        raise DownloadError(
            f"Failed to get download URL for volume {vol_id} from all lines {list(lines)}: {last_error}"
        ) from last_error

    return urls


# ---------------------------------------------------------------------------
# Single-volume download
# ---------------------------------------------------------------------------


def _should_skip_volume(
    config: AppConfig,
    comic_id: str,
    title: str,
    vol_id: str,
    format_name: str,
    dest: Path,
    volume: Volume,
) -> bool:
    """Check whether a volume should be skipped.

    A volume is skipped when the library already records it **and** the file
    exists on disk with a plausible size (within 10 MB of the expected size,
    or any size when no expected size is available).
    """
    entry = load_entry(config, comic_id, title)
    if entry is None:
        return False

    recorded = any(v.vol_id == vol_id and v.format == format_name for v in entry.downloaded_volumes)
    if not recorded:
        return False

    if not dest.exists():
        return False

    # Compare actual file size against expected size if available
    expected_mb = volume.size_epub_mb if format_name == "epub" else volume.size_mobi_mb
    if expected_mb > 0:
        actual_mb = dest.stat().st_size / (1024 * 1024)
        if abs(actual_mb - expected_mb) > 10:
            return False

    return True


async def download_volume(
    client: KmoeClient,
    config: AppConfig,
    detail: ComicDetail,
    vol_id: str,
    fmt: DownloadFormat,
    *,
    progress_callback: Callable[[int], None] | None = None,
    total_callback: Callable[[int], None] | None = None,
) -> DownloadResult:
    """Download a single volume to the local library.

    Args:
        client: The HTTP client to use.
        config: Application configuration.
        detail: The comic detail (metadata + volume list).
        vol_id: The volume ID to download.
        fmt: The desired download format.
        progress_callback: Optional callback invoked with the number of bytes
            received for each chunk.
        total_callback: Optional callback invoked once with the total size in
            bytes (from Content-Length) before streaming begins.

    Returns:
        A :class:`DownloadResult` describing the outcome.

    Raises:
        DownloadError: When the download fails.
        VolumeNotFoundError: When *vol_id* is not in *detail.volumes*.
    """
    book_id = detail.meta.book_id
    comic_id = detail.meta.comic_id or book_id
    title = detail.meta.title
    format_name = _FORMAT_NAMES[fmt]

    # Resolve the volume object
    volume = find_volume(detail, vol_id)

    # Determine destination path (use comic_id for directory naming)
    comic_dir = get_comic_dir(config, comic_id, title)
    filename = f"[Kmoe][{sanitize_filename(title)}]{volume.title}.{format_name}"
    dest = comic_dir / filename

    # Skip if already downloaded and file looks valid
    if _should_skip_volume(config, comic_id, title, vol_id, format_name, dest, volume):
        log.info(
            "volume already downloaded, skipping",
            book_id=book_id,
            vol_id=vol_id,
            format=format_name,
        )
        return DownloadResult(
            path=dest,
            volume=volume,
            skipped=True,
            size_bytes=dest.stat().st_size if dest.exists() else 0,
        )

    # Get download URLs from multiple lines for fallback
    try:
        urls = await get_download_urls(
            client=client,
            book_id=book_id,
            vol_id=vol_id,
            fmt=fmt,
        )
    except Exception as exc:
        raise DownloadError(f"Failed to get download URL for volume {vol_id}: {exc}") from exc

    log.info(
        "downloading volume",
        book_id=book_id,
        vol_id=vol_id,
        title=volume.title,
        format=format_name,
    )

    # Try each URL until one succeeds
    last_error: Exception | None = None
    for url in urls:
        try:
            await client.download_file(
                url, dest, progress_callback=progress_callback, total_callback=total_callback
            )
            last_error = None
            break
        except Exception as exc:
            log.warning("download failed, trying next url", url=url, error=str(exc))
            last_error = exc

    if last_error is not None:
        raise DownloadError(
            f"Failed to download volume {vol_id} ({volume.title}): {last_error}"
        ) from last_error

    # Record in library
    size_bytes = dest.stat().st_size if dest.exists() else 0

    entry = load_entry(config, comic_id, title)
    if entry is None:
        entry = LibraryEntry(
            book_id=book_id,
            comic_id=comic_id,
            title=title,
            meta=detail.meta,
        )

    downloaded_vol = DownloadedVolume(
        vol_id=vol_id,
        title=volume.title,
        format=format_name,
        filename=filename,
        downloaded_at=datetime.now(timezone.utc),
        size_bytes=size_bytes,
    )
    # Deduplicate and append
    entry.downloaded_volumes[:] = [
        v for v in entry.downloaded_volumes if not (v.vol_id == vol_id and v.format == format_name)
    ]
    entry.downloaded_volumes.append(downloaded_vol)
    # Refresh metadata, total_volumes, is_complete from remote detail
    entry = refresh_entry_from_detail(entry, detail)
    save_entry(config, entry)

    log.info(
        "volume downloaded",
        book_id=book_id,
        vol_id=vol_id,
        size_bytes=size_bytes,
        path=str(dest),
    )

    return DownloadResult(
        path=dest,
        volume=volume,
        skipped=False,
        size_bytes=size_bytes,
    )


# ---------------------------------------------------------------------------
# Multi-volume download
# ---------------------------------------------------------------------------


async def download_volumes(
    client: KmoeClient,
    config: AppConfig,
    detail: ComicDetail,
    vol_ids: list[str],
    fmt: DownloadFormat,
    *,
    progress_callback: Callable[[int], None] | None = None,
) -> BatchDownloadResult:
    """Download multiple volumes concurrently with semaphore control.

    Limits concurrent downloads to config.max_download_workers to avoid
    overwhelming the server while still respecting rate limits.
    Individual volume failures are captured and do not abort other downloads.

    Args:
        client: The HTTP client to use.
        config: Application configuration.
        detail: The comic detail (metadata + volume list).
        vol_ids: List of volume IDs to download.
        fmt: The desired download format.
        progress_callback: Optional progress callback forwarded to each download.

    Returns:
        A :class:`BatchDownloadResult` with successful results and any errors.
    """
    results: list[DownloadResult] = []
    errors: list[tuple[str, Exception]] = []

    semaphore = asyncio.Semaphore(config.max_download_workers)

    async def bounded_download(vol_id: str) -> DownloadResult | tuple[str, Exception]:
        async with semaphore:
            try:
                return await download_volume(
                    client,
                    config,
                    detail,
                    vol_id,
                    fmt,
                    progress_callback=progress_callback,
                )
            except Exception as exc:
                log.error(
                    "failed to download volume",
                    vol_id=vol_id,
                    error=str(exc),
                )
                return (vol_id, exc)

    tasks = [bounded_download(vol_id) for vol_id in vol_ids]
    results_raw = await asyncio.gather(*tasks, return_exceptions=False)

    for item in results_raw:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], Exception):
            errors.append(item)  # type: ignore[arg-type]
        else:
            results.append(item)  # type: ignore[arg-type]

    return BatchDownloadResult(results=results, errors=errors)
