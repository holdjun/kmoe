"""Utility functions for the Kmoe manga downloader."""

import logging
import re
from pathlib import Path

import structlog


def sanitize_filename(name: str) -> str:
    """Clean a string for use as a filename.

    Args:
        name: The string to sanitize.

    Returns:
        A sanitized filename string safe for most filesystems.

    Example:
        >>> sanitize_filename('My Comic: Vol 1?')
        'My Comic_ Vol 1_'
        >>> sanitize_filename('   ...   ')
        'unnamed'
    """
    # Replace invalid characters with underscore
    invalid_chars = r'[/\\:*?"<>|]'
    sanitized = re.sub(invalid_chars, "_", name)

    # Strip leading/trailing whitespace and dots
    sanitized = sanitized.strip().strip(".")

    # Truncate to 200 characters max
    sanitized = sanitized[:200]

    # Return 'unnamed' if empty after sanitization
    return sanitized if sanitized else "unnamed"


def parse_size(size_str: str) -> int:
    """Parse human-readable size string to bytes.

    Supports formats like "52.3 MB", "1.2 GB", "500 KB", "1024 B".
    Case-insensitive.

    Args:
        size_str: The size string to parse (e.g., "52.3 MB").

    Returns:
        The size in bytes, or 0 if parsing fails.

    Example:
        >>> parse_size("52.3 MB")
        54835609
        >>> parse_size("1.2 GB")
        1288490188
        >>> parse_size("invalid")
        0
    """
    # Pattern to match number and unit
    pattern = r"^\s*([0-9]+\.?[0-9]*)\s*([A-Za-z]+)\s*$"
    match = re.match(pattern, size_str)

    if not match:
        return 0

    try:
        value = float(match.group(1))
        unit = match.group(2).upper()

        # Convert to bytes based on unit
        multipliers = {
            "B": 1,
            "KB": 1024,
            "MB": 1024**2,
            "GB": 1024**3,
            "TB": 1024**4,
        }

        multiplier = multipliers.get(unit, 0)
        if multiplier == 0:
            return 0

        return int(value * multiplier)
    except (ValueError, OverflowError):
        return 0


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string.

    Args:
        size_bytes: The size in bytes.

    Returns:
        A human-readable size string (e.g., "50.0 MB").

    Example:
        >>> format_size(52428800)
        '50.0 MB'
        >>> format_size(1024)
        '1.0 KB'
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.1f} GB"


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return it.

    Args:
        path: The directory path to create.

    Returns:
        The same path (for chaining).

    Example:
        >>> ensure_dir(Path("/tmp/test_dir"))
        PosixPath('/tmp/test_dir')
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    """Get the data directory path.

    Uses ~/.config/kmoe on macOS/Linux. Creates it if it doesn't exist.

    Returns:
        The data directory path.

    Example:
        >>> get_data_dir()
        PosixPath('/Users/username/.config/kmoe')
    """
    data_dir = Path.home() / ".config" / "kmoe"
    return ensure_dir(data_dir)


def setup_logging(verbose: bool = False) -> None:
    """Configure structlog with colorful console output.

    Args:
        verbose: If True, set log level to DEBUG, else INFO.

    Example:
        >>> setup_logging(verbose=True)
    """
    # Set the log level
    log_level = logging.DEBUG if verbose else logging.INFO

    # Configure stdlib logging (structlog will integrate with it)
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )

    # Configure structlog with colorful console output
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def extract_comic_id_from_url(url: str) -> str:
    """Extract comic ID from Kmoe URL.

    Args:
        url: The Kmoe URL (e.g., "https://kxx.moe/c/18488.htm").

    Returns:
        The comic ID extracted from the URL.

    Raises:
        ValueError: If the URL doesn't match the expected pattern.

    Example:
        >>> extract_comic_id_from_url("https://kxx.moe/c/18488.htm")
        '18488'
        >>> extract_comic_id_from_url("https://kzz.moe/c/abc123.htm")
        'abc123'
    """
    # Pattern to match /c/{id}.htm
    pattern = r"/c/([^/]+?)\.htm"
    match = re.search(pattern, url)

    if not match:
        raise ValueError(f"Could not extract comic ID from URL: {url}")

    return match.group(1)
