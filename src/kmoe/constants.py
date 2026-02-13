"""Constants for the Kmoe manga downloader CLI tool."""

from enum import IntEnum
from pathlib import Path

# Application name
APP_NAME = "kmoe"

# Mirror domains
MIRROR_DOMAINS: tuple[str, ...] = (
    "kxx.moe",
    "kzz.moe",
    "koz.moe",
)

DEFAULT_DOMAIN = MIRROR_DOMAINS[0]


class DownloadFormat(IntEnum):
    """Download format options."""

    MOBI = 1
    EPUB = 2


# Language codes for category search
LANGUAGE_CODES: tuple[str, ...] = ("all", "ch", "jp", "en", "oth")


# URL templates
class URLTemplate:
    """URL templates for various endpoints."""

    COMIC_DETAIL = "https://{domain}/c/{comic_id}.htm"
    SEARCH = "https://{domain}/list.php?s={keyword}"
    CATEGORY_BROWSE = "https://{domain}/l/{filters}/{page}.htm"
    DOWNLOAD = "https://{domain}/dl/{book_id}/{vol_id}/{line}/{format_code}/{file_count}/"
    BATCH_DOWNLOAD = (
        "https://{domain}/getdownurl.php?b={book_id}&v=1&vip=9&mobi={format_code}&batch={vol_list}"
    )
    LOGIN = "https://{domain}/login_do.php"
    HOME = "https://{domain}/"
    MY = "https://{domain}/my.php"


# Default User-Agent string (Chrome on macOS)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Default HTTP headers
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8,zh-CN;q=0.7,zh;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Rate limiting
DEFAULT_RATE_LIMIT_DELAY: float = 1.0  # seconds

# Retry settings
DEFAULT_MAX_RETRIES: int = 3

# Default directories
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"
DEFAULT_CONFIG_DIR = DEFAULT_DATA_DIR / "config"
DEFAULT_DOWNLOAD_DIR = DEFAULT_DATA_DIR / "downloads"
DEFAULT_CACHE_DIR = DEFAULT_DATA_DIR / "cache"


def get_data_dir() -> Path:
    """Get the data directory, using platformdirs if available."""
    try:
        from platformdirs import user_data_dir

        return Path(user_data_dir(APP_NAME))
    except ImportError:
        return DEFAULT_DATA_DIR


def get_config_dir() -> Path:
    """Get the config directory, using platformdirs if available."""
    try:
        from platformdirs import user_config_dir

        return Path(user_config_dir(APP_NAME))
    except ImportError:
        return DEFAULT_CONFIG_DIR


def get_cache_dir() -> Path:
    """Get the cache directory, using platformdirs if available."""
    try:
        from platformdirs import user_cache_dir

        return Path(user_cache_dir(APP_NAME))
    except ImportError:
        return DEFAULT_CACHE_DIR
