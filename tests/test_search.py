"""Tests for kmoe.search module."""

from __future__ import annotations

from kmoe.models import SearchResult
from kmoe.search import sort_by_language_and_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    comic_id: str = "1",
    title: str = "Test",
    language: str = "中文",
    score: float | None = None,
) -> SearchResult:
    return SearchResult(comic_id=comic_id, title=title, language=language, score=score)


# ---------------------------------------------------------------------------
# sort_by_language_and_score
# ---------------------------------------------------------------------------


class TestSortByLanguageAndScore:
    """Given a list of SearchResult items with mixed languages and scores."""

    def test_preferred_language_first(self) -> None:
        """When preferred language is 'ch' (中文),
        then 中文 results appear before 日語 results."""
        results = [
            _result("1", language="日語", score=9.5),
            _result("2", language="中文", score=7.0),
        ]
        sorted_results = sort_by_language_and_score(results, "ch")
        assert sorted_results[0].comic_id == "2"
        assert sorted_results[1].comic_id == "1"

    def test_higher_score_first_within_same_language(self) -> None:
        """When multiple results share the preferred language,
        then they are sorted by score descending."""
        results = [
            _result("1", language="中文", score=7.0),
            _result("2", language="中文", score=9.5),
            _result("3", language="中文", score=8.0),
        ]
        sorted_results = sort_by_language_and_score(results, "ch")
        assert [r.comic_id for r in sorted_results] == ["2", "3", "1"]

    def test_none_score_treated_as_zero(self) -> None:
        """When a result has score=None,
        then it is treated as 0 for sorting purposes."""
        results = [
            _result("1", language="中文", score=None),
            _result("2", language="中文", score=5.0),
        ]
        sorted_results = sort_by_language_and_score(results, "ch")
        assert sorted_results[0].comic_id == "2"

    def test_empty_list_returns_empty(self) -> None:
        """Given an empty results list,
        when sorted,
        then an empty list is returned."""
        assert sort_by_language_and_score([], "ch") == []

    def test_japanese_preferred(self) -> None:
        """When preferred language is 'jp' (日語),
        then 日語 results appear before 中文 results."""
        results = [
            _result("1", language="中文", score=9.5),
            _result("2", language="日語", score=7.0),
        ]
        sorted_results = sort_by_language_and_score(results, "jp")
        assert sorted_results[0].comic_id == "2"

    def test_all_language_no_preference(self) -> None:
        """When preferred language is 'all',
        then all results are treated equally and sorted by score only."""
        results = [
            _result("1", language="中文", score=7.0),
            _result("2", language="日語", score=9.0),
            _result("3", language="英文", score=8.0),
        ]
        sorted_results = sort_by_language_and_score(results, "all")
        # 'all' has no matching display name, so all get priority 1 -> sorted by score
        assert [r.comic_id for r in sorted_results] == ["2", "3", "1"]
