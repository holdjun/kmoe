"""Pytest fixtures for kmoe tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def comic_detail_html() -> str:
    """Read and return comic_detail_18488.html fixture."""
    return (FIXTURES_DIR / "comic_detail_18488.html").read_text(encoding="utf-8")


@pytest.fixture
def book_data_html() -> str:
    """Read and return book_data_18488.html fixture."""
    return (FIXTURES_DIR / "book_data_18488.html").read_text(encoding="utf-8")


@pytest.fixture
def search_results_html() -> str:
    """Read and return search_results.html fixture."""
    return (FIXTURES_DIR / "search_results.html").read_text(encoding="utf-8")


@pytest.fixture
def search_empty_html() -> str:
    """Read and return search_empty.html fixture."""
    return (FIXTURES_DIR / "search_empty.html").read_text(encoding="utf-8")


@pytest.fixture
def login_page_html() -> str:
    """Read and return login_page.html fixture."""
    return (FIXTURES_DIR / "login_page.html").read_text(encoding="utf-8")


@pytest.fixture
def home_page_html() -> str:
    """Read and return home_page.html fixture."""
    return (FIXTURES_DIR / "home_page.html").read_text(encoding="utf-8")
