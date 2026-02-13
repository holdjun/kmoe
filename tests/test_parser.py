"""Tests for kmoe.parser module."""

from __future__ import annotations

import pytest

from kmoe.parser import (
    extract_book_data_url,
    extract_js_variables,
    parse_comic_detail,
    parse_search_results,
    parse_volume_data,
)

# ---------------------------------------------------------------------------
# parse_search_results
# ---------------------------------------------------------------------------


class TestParseSearchResults:
    """Given search results HTML from the Kmoe site."""

    def test_extracts_all_results(self, search_results_html: str) -> None:
        """When parsing a page with 21 results,
        then all 21 SearchResult items are returned."""
        response = parse_search_results(search_results_html)
        assert len(response.results) == 21

    def test_first_result_comic_id(self, search_results_html: str) -> None:
        """When parsing the first result,
        then its comic_id is correctly extracted from the URL."""
        result = parse_search_results(search_results_html).results[0]
        assert result.comic_id == "18488"

    def test_first_result_title_strips_html(self, search_results_html: str) -> None:
        """When parsing a title with <b> tags,
        then the HTML is stripped, leaving plain text."""
        result = parse_search_results(search_results_html).results[0]
        assert "<b>" not in result.title
        assert "SAKAMOTO" in result.title

    def test_first_result_metadata(self, search_results_html: str) -> None:
        """When parsing the first result,
        then score, author, and status are correctly extracted."""
        result = parse_search_results(search_results_html).results[0]
        assert result.score == pytest.approx(9.1)
        assert result.authors == ["鈴木祐鬥"]
        assert result.status == "連載"

    def test_completed_comic_status(self, search_results_html: str) -> None:
        """Given a search result where tag_end is empty,
        when parsed,
        then status is '完結'."""
        # 10288 "在下坂本,有何貴幹?" has tag_end=""
        result = parse_search_results(search_results_html).results[1]
        assert result.comic_id == "10288"
        assert result.status == "完結"

    def test_japanese_language_detection(self, search_results_html: str) -> None:
        """Given a search result where tag_jp is empty,
        when parsed,
        then language is '日語'."""
        # 21208 has tag_jp=""
        result = parse_search_results(search_results_html).results[2]
        assert result.comic_id == "21208"
        assert result.language == "日語"

    def test_english_language_detection(self, search_results_html: str) -> None:
        """Given a search result where tag_en is empty,
        when parsed,
        then language is '英文'."""
        # 27091 has tag_en=""
        result = parse_search_results(search_results_html).results[3]
        assert result.comic_id == "27091"
        assert result.language == "英文"

    def test_chinese_language_default(self, search_results_html: str) -> None:
        """Given a search result where both tag_jp and tag_en are non-empty,
        when parsed,
        then language defaults to '中文'."""
        result = parse_search_results(search_results_html).results[0]
        assert result.language == "中文"

    def test_pagination_info(self, search_results_html: str) -> None:
        """When parsing a paginated search page,
        then total_pages and current_page are extracted."""
        response = parse_search_results(search_results_html)
        assert response.total_pages == 8
        assert response.current_page == 1

    def test_empty_results(self, search_empty_html: str) -> None:
        """Given an empty search result page,
        when parsed,
        then results list is empty and total_pages is 0."""
        response = parse_search_results(search_empty_html)
        assert response.results == []
        assert response.total_pages == 0


# ---------------------------------------------------------------------------
# parse_volume_data
# ---------------------------------------------------------------------------


class TestParseVolumeData:
    """Given book_data.php HTML response with volinfo postMessage calls."""

    def test_extracts_all_volumes(self, book_data_html: str) -> None:
        """When parsing volume data,
        then all 37 volumes are extracted."""
        volumes = parse_volume_data(book_data_html)
        assert len(volumes) == 37

    def test_first_volume_fields(self, book_data_html: str) -> None:
        """When parsing the first volume,
        then vol_id, title, and file_count are correct."""
        vol = parse_volume_data(book_data_html)[0]
        assert vol.vol_id == "1001"
        assert vol.title == "卷 01"
        assert vol.file_count == 190

    def test_volume_sizes_extracted(self, book_data_html: str) -> None:
        """When parsing volume data,
        then MOBI and EPUB sizes in MB are extracted."""
        vol = parse_volume_data(book_data_html)[0]
        assert vol.size_mobi_mb == pytest.approx(88.2)
        assert vol.size_epub_mb == pytest.approx(85.4)

    def test_special_volume_type(self, book_data_html: str) -> None:
        """When parsing a non-standard volume (e.g. 番外篇),
        then it is correctly extracted with its own vol_id."""
        volumes = parse_volume_data(book_data_html)
        special = next(v for v in volumes if v.vol_id == "2001")
        assert special.title == "短篇"
        assert special.file_count == 48

    def test_chapter_group_volume(self, book_data_html: str) -> None:
        """When parsing a chapter-group volume (話),
        then its title contains the chapter range."""
        volumes = parse_volume_data(book_data_html)
        chapter = next(v for v in volumes if v.vol_id == "3151")
        assert chapter.title == "話 151-155"

    def test_empty_html_returns_empty_list(self) -> None:
        """Given HTML with no volinfo messages,
        when parsed,
        then an empty list is returned."""
        assert parse_volume_data("<html></html>") == []


# ---------------------------------------------------------------------------
# parse_comic_detail
# ---------------------------------------------------------------------------


class TestParseComicDetail:
    """Given comic detail HTML from the Kmoe site."""

    def test_extracts_book_id(self, comic_detail_html: str) -> None:
        """When parsing the detail page,
        then the book_id is extracted from JS variables."""
        detail = parse_comic_detail(comic_detail_html)
        assert detail.meta.book_id == "18488"

    def test_extracts_title_and_author(self, comic_detail_html: str) -> None:
        """When parsing the detail page,
        then title and author are extracted from the <title> tag."""
        detail = parse_comic_detail(comic_detail_html)
        assert "SAKAMOTO DAYS" in detail.meta.title
        assert len(detail.meta.authors) >= 1

    def test_volumes_initially_empty(self, comic_detail_html: str) -> None:
        """When parsing the detail page alone (no book_data),
        then volumes list is empty (loaded separately)."""
        detail = parse_comic_detail(comic_detail_html)
        assert detail.volumes == []


# ---------------------------------------------------------------------------
# extract_book_data_url
# ---------------------------------------------------------------------------


class TestExtractBookDataUrl:
    """Given comic detail HTML containing the book_data.php URL."""

    def test_extracts_url_path(self, comic_detail_html: str) -> None:
        """When the HTML contains an iframe_action2 href assignment,
        then the /book_data.php path is extracted."""
        url = extract_book_data_url(comic_detail_html)
        assert url is not None
        assert url.startswith("/book_data.php?h=")

    def test_returns_none_for_missing(self) -> None:
        """Given HTML without book_data reference,
        when extracted,
        then None is returned."""
        assert extract_book_data_url("<html></html>") is None


# ---------------------------------------------------------------------------
# extract_js_variables
# ---------------------------------------------------------------------------


class TestExtractJsVariables:
    """Given HTML with embedded JS variable declarations."""

    def test_extracts_bookid(self) -> None:
        """When HTML contains 'var bookid = "18488";',
        then bookid is extracted."""
        html = '<script>var bookid = "18488";</script>'
        assert extract_js_variables(html)["bookid"] == "18488"

    def test_extracts_uin(self) -> None:
        """When HTML contains 'var uin = "user@email.com";',
        then uin is extracted."""
        html = '<script>var uin = "user@email.com";</script>'
        assert extract_js_variables(html)["uin"] == "user@email.com"

    def test_extracts_parseint_value(self) -> None:
        """When HTML contains 'var ulevel = parseInt("3");',
        then the inner value is extracted."""
        html = '<script>var ulevel = parseInt("3");</script>'
        assert extract_js_variables(html)["ulevel"] == "3"

    def test_ignores_irrelevant_vars(self) -> None:
        """When HTML contains vars not in the target set,
        then they are not included in the result."""
        html = '<script>var foo = "bar"; var bookid = "123";</script>'
        result = extract_js_variables(html)
        assert "foo" not in result
        assert result["bookid"] == "123"
