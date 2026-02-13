"""Search and browse functionality for the Kmoe manga downloader."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from kmoe.constants import URLTemplate
from kmoe.parser import parse_search_results

if TYPE_CHECKING:
    from kmoe.client import KmoeClient
    from kmoe.models import SearchResponse, SearchResult


# Mapping from config language codes to display values
LANG_CODE_TO_DISPLAY: dict[str, str] = {
    "ch": "中文",
    "jp": "日語",
    "en": "英文",
}

# Mapping from simple codes to API codes (for website requests)
LANG_CODE_TO_API: dict[str, str] = {
    "ch": "chn",
    "jp": "jpn",
    "en": "eng",
    "oth": "oth",
}


def sort_by_language_and_score(
    results: list[SearchResult],
    preferred_language: str,
) -> list[SearchResult]:
    """Sort search results by preferred language first, then by score descending.

    Args:
        results: List of search results to sort.
        preferred_language: Language code (ch, jp, en, oth, all).

    Returns:
        Sorted list of search results.
    """
    if not results:
        return results

    # Get the display language for the preferred code
    preferred_display = LANG_CODE_TO_DISPLAY.get(preferred_language, "")

    def sort_key(r: SearchResult) -> tuple[int, float]:
        # Preferred language gets priority 0, others get 1
        lang_priority = 0 if r.language == preferred_display else 1
        # Higher score is better (negate for descending)
        score = r.score if r.score else 0
        return (lang_priority, -score)

    return sorted(results, key=sort_key)


async def search(
    client: KmoeClient,
    keyword: str,
    page: int = 1,
    language: str = "all",
) -> SearchResponse:
    """Search for comics by keyword.

    Args:
        client: The HTTP client to use for requests.
        keyword: Search keyword (comic title or author name).
        page: Page number for paginated results (1-based).
        language: Language filter (all, ch, jp, en, oth).

    Returns:
        SearchResponse containing matching results and pagination info.
    """
    if language != "all":
        # Map simple code to API code
        api_lang = LANG_CODE_TO_API.get(language, language)
        # Use category browse endpoint with language filter
        filters = f"{quote(keyword)},all,all,sortpoint,{api_lang},all,BL,0,0"
        response = await client.get(
            URLTemplate.CATEGORY_BROWSE,
            filters=filters,
            page=str(page),
        )
    else:
        # Use the simpler list.php endpoint
        url_template = URLTemplate.SEARCH
        if page > 1:
            url_template += "&page={page}"
            response = await client.get(url_template, keyword=keyword, page=str(page))
        else:
            response = await client.get(url_template, keyword=keyword)

    return parse_search_results(response.text)
