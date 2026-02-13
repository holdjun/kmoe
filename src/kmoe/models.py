"""Pydantic data models for the Kmoe manga downloader."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Comic metadata & detail
# ---------------------------------------------------------------------------


class ComicMeta(BaseModel):
    """Core metadata for a comic (manga/manhua/manhwa)."""

    model_config = ConfigDict(frozen=True)

    book_id: str
    comic_id: str = ""
    title: str
    authors: list[str] = []
    status: str = ""
    region: str = ""
    language: str = ""
    categories: list[str] = []
    score: float | None = None
    cover_url: str = ""
    description: str = ""


class Volume(BaseModel):
    """A single volume or chapter available for download."""

    model_config = ConfigDict(frozen=True)

    vol_id: str
    title: str
    file_count: int = 1
    size_mobi_mb: float = 0.0
    size_epub_mb: float = 0.0


class ComicDetail(BaseModel):
    """Full comic information including all available volumes."""

    meta: ComicMeta
    volumes: list[Volume] = []


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchResult(BaseModel):
    """A single item returned from a search query."""

    model_config = ConfigDict(frozen=True)

    comic_id: str
    title: str
    authors: list[str] = []
    cover_url: str = ""
    last_update: str = ""
    score: float | None = None
    status: str = ""  # 連載/完結/停更
    language: str = ""  # 中文/日語/英文


class SearchResponse(BaseModel):
    """Paginated collection of search results."""

    results: list[SearchResult]
    total_pages: int = 1
    current_page: int = 1


# ---------------------------------------------------------------------------
# Local library
# ---------------------------------------------------------------------------


class DownloadedVolume(BaseModel):
    """Record of a volume that has been downloaded to disk."""

    vol_id: str
    title: str
    format: str
    filename: str
    downloaded_at: datetime
    size_bytes: int = 0


class LibraryEntry(BaseModel):
    """A comic tracked in the user's local library."""

    book_id: str
    comic_id: str = ""
    title: str
    meta: ComicMeta
    downloaded_volumes: list[DownloadedVolume] = []
    total_volumes: int = 0
    last_checked: datetime | None = None
    is_complete: bool = False


class LibraryIndexEntry(BaseModel):
    """Summary entry for a comic in the root library index."""

    book_id: str
    title: str
    dir_name: str
    authors: list[str] = []
    status: str = ""
    total_volumes: int = 0
    downloaded_volumes: int = 0
    is_complete: bool = False


class LibraryIndex(BaseModel):
    """Root-level library index aggregating all comics."""

    version: str = "1.0"
    updated_at: datetime
    comics: list[LibraryIndexEntry] = []


# ---------------------------------------------------------------------------
# User / session
# ---------------------------------------------------------------------------


class UserStatus(BaseModel):
    """Status of the currently logged-in user."""

    model_config = ConfigDict(frozen=True)

    uin: str = ""
    username: str = ""
    level: int = 0
    is_vip: bool = False
    quota_now: float = 0.0
    # Detailed quota breakdown (in MB)
    quota_free_month: float = 0.0  # 每月免費額度
    quota_remaining: float = 0.0  # 剩餘
    quota_extra: float = 0.0  # 額外額度剩餘


# ---------------------------------------------------------------------------
# Application configuration (plain dataclass, NOT a Pydantic model)
# ---------------------------------------------------------------------------


@dataclass
class AppConfig:
    """Application-level configuration.

    This is intentionally a plain dataclass rather than a Pydantic model so
    that it can be mutated freely at runtime and carries no serialisation
    overhead.
    """

    download_dir: Path = field(default_factory=lambda: Path.home() / "kmoe-library")
    default_format: str = "epub"
    preferred_mirror: str = "kxx.moe"
    mirror_failover: bool = True
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    preferred_language: str = "all"
    max_download_workers: int = 2
