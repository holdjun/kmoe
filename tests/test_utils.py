"""Tests for kmoe.utils module."""

from __future__ import annotations

import pytest

from kmoe.utils import (
    extract_comic_id_from_url,
    format_size,
    parse_size,
    sanitize_filename,
)

# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    """Given various strings to use as filenames."""

    def test_replaces_invalid_characters(self) -> None:
        """When the name contains /\\:*?"<>|, then they become underscores."""
        assert sanitize_filename("My Comic: Vol 1?") == "My Comic_ Vol 1_"

    def test_strips_leading_trailing_whitespace_and_dots(self) -> None:
        """When the name has surrounding whitespace and dots, they are removed."""
        assert sanitize_filename("  ..hello..  ") == "hello"

    def test_truncates_to_200_characters(self) -> None:
        """When the name exceeds 200 characters, it is truncated."""
        long_name = "a" * 300
        assert len(sanitize_filename(long_name)) == 200

    def test_empty_string_returns_unnamed(self) -> None:
        """When the name is empty after sanitization, 'unnamed' is returned."""
        assert sanitize_filename("") == "unnamed"

    def test_only_dots_returns_unnamed(self) -> None:
        """When the name is only dots/spaces, 'unnamed' is returned."""
        assert sanitize_filename("   ...   ") == "unnamed"

    def test_preserves_unicode(self) -> None:
        """When the name contains CJK characters, they are preserved."""
        assert sanitize_filename("棋魂 Vol 01") == "棋魂 Vol 01"


# ---------------------------------------------------------------------------
# parse_size
# ---------------------------------------------------------------------------


class TestParseSize:
    """Given human-readable size strings."""

    def test_megabytes(self) -> None:
        assert parse_size("52.3 MB") == int(52.3 * 1024**2)

    def test_gigabytes(self) -> None:
        assert parse_size("1.2 GB") == int(1.2 * 1024**3)

    def test_kilobytes(self) -> None:
        assert parse_size("500 KB") == 500 * 1024

    def test_bytes(self) -> None:
        assert parse_size("1024 B") == 1024

    def test_case_insensitive(self) -> None:
        assert parse_size("10 mb") == (10 * 1024**2)

    def test_invalid_string_returns_zero(self) -> None:
        assert parse_size("invalid") == 0

    def test_empty_string_returns_zero(self) -> None:
        assert parse_size("") == 0

    def test_unknown_unit_returns_zero(self) -> None:
        assert parse_size("10 XB") == 0


# ---------------------------------------------------------------------------
# format_size
# ---------------------------------------------------------------------------


class TestFormatSize:
    """Given sizes in bytes."""

    def test_bytes(self) -> None:
        assert format_size(500) == "500 B"

    def test_kilobytes(self) -> None:
        assert format_size(1024) == "1.0 KB"

    def test_megabytes(self) -> None:
        assert format_size(52428800) == "50.0 MB"

    def test_gigabytes(self) -> None:
        assert format_size(1073741824) == "1.0 GB"

    def test_zero(self) -> None:
        assert format_size(0) == "0 B"


# ---------------------------------------------------------------------------
# extract_comic_id_from_url
# ---------------------------------------------------------------------------


class TestExtractComicIdFromUrl:
    """Given Kmoe URLs."""

    def test_numeric_id(self) -> None:
        assert extract_comic_id_from_url("https://kxx.moe/c/18488.htm") == "18488"

    def test_hex_id(self) -> None:
        assert extract_comic_id_from_url("https://kzz.moe/c/abc123.htm") == "abc123"

    def test_with_path_prefix(self) -> None:
        assert extract_comic_id_from_url("https://kxx.moe/c/425daf.htm") == "425daf"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not extract"):
            extract_comic_id_from_url("https://kxx.moe/search?q=test")
