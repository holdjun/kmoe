"""Comic detail and download URL parsing for the Kmoe manga downloader."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kmoe.constants import DownloadFormat, URLTemplate
from kmoe.exceptions import ComicNotFoundError, MirrorExhaustedError, VolumeNotFoundError
from kmoe.models import ComicDetail
from kmoe.parser import extract_book_data_url, parse_comic_detail, parse_volume_data

if TYPE_CHECKING:
    from kmoe.client import KmoeClient
    from kmoe.models import Volume


async def get_comic_detail(client: KmoeClient, comic_id: str) -> ComicDetail:
    """Fetch full comic detail including volumes.

    Args:
        client: The HTTP client to use for requests.
        comic_id: The unique identifier for the comic (URL-form ID, typically hexadecimal).

    Returns:
        ComicDetail containing metadata and volume list.

    Raises:
        ComicNotFoundError: If the comic does not exist (HTTP 404 on all mirrors).
    """
    try:
        response = await client.get(URLTemplate.COMIC_DETAIL, comic_id=comic_id)
    except MirrorExhaustedError:
        # All mirrors returned 404 (or other failover errors)
        raise ComicNotFoundError(comic_id) from None

    if response.status_code == 404:
        raise ComicNotFoundError(comic_id)

    html = response.text
    detail = parse_comic_detail(html)

    # Write the URL-form comic_id into meta (book_id is already extracted from JS)
    if not detail.meta.comic_id:
        detail = ComicDetail(
            meta=detail.meta.model_copy(update={"comic_id": comic_id}),
            volumes=detail.volumes,
        )

    # Fetch volume data from separate endpoint
    book_data_path = extract_book_data_url(html)
    if book_data_path:
        vol_response = await client.get("https://{domain}" + book_data_path)
        volumes = parse_volume_data(vol_response.text)
        detail.volumes = volumes

    return detail


def build_download_url(
    domain: str,
    book_id: str,
    volume: Volume,
    format: DownloadFormat,
    line: int = 0,
) -> str:
    """Build a download URL for a specific volume.

    Args:
        domain: The mirror domain to use (e.g. "kxx.moe").
        book_id: The comic's book ID.
        volume: The volume to download.
        format: The download format (MOBI, or EPUB).
        line: Download server line, typically 0 for the default server.

    Returns:
        The fully formatted download URL string.
    """
    return URLTemplate.DOWNLOAD.format(
        domain=domain,
        book_id=book_id,
        vol_id=volume.vol_id,
        line=line,
        format_code=int(format),
        file_count=volume.file_count,
    )


def find_volume(detail: ComicDetail, vol_id: str) -> Volume:
    """Find a specific volume in a comic's volume list.

    Args:
        detail: The comic detail containing the volume list.
        vol_id: The volume ID to search for.

    Returns:
        The matching Volume object.

    Raises:
        VolumeNotFoundError: If no volume with the given ID exists.
    """
    for volume in detail.volumes:
        if volume.vol_id == vol_id:
            return volume

    raise VolumeNotFoundError(vol_id)
