"""HTML parsing module for the Kmoe manga downloader."""

from __future__ import annotations

import contextlib
import re
from typing import Any

from selectolax.parser import HTMLParser

from kmoe.models import (
    ComicDetail,
    ComicMeta,
    SearchResponse,
    SearchResult,
    UserStatus,
    Volume,
)


def _get_text(node: Any, default: str = "") -> str:
    """Safely extract text from a node, returning default if node is None."""
    if node is None:
        return default
    text = node.text(strip=True)
    return text if text else default


def _get_attr(node: Any, attr: str, default: str = "") -> str:
    """Safely extract an attribute from a node, returning default if node is None."""
    if node is None:
        return default
    value = node.attributes.get(attr)
    return value if value else default


def extract_js_variables(html: str) -> dict[str, str]:
    """Extract JS variables from <script> tags.

    Looks for patterns like: var bookid = "18488"; or var ulevel = parseInt("3");
    Returns a dict mapping variable names to their string values.
    """
    variables: dict[str, str] = {}

    # Pattern for simple assignment: var name = value;
    # Handles quotes, parseInt(), and bare values
    patterns = [
        # var name = "value"; or var name = 'value';
        r'var\s+(\w+)\s*=\s*["\']([^"\']*)["\']',
        # var name = parseInt("value"); or parseInt('value')
        r'var\s+(\w+)\s*=\s*parseInt\s*\(\s*["\']([^"\']*)["\']',
        # var name = value; (bare number or identifier)
        r"var\s+(\w+)\s*=\s*(\d+(?:\.\d+)?)\s*;",
    ]

    target_vars = {"bookid", "uin", "ulevel", "is_vip", "quota_now", "bookstatus", "device_mailto"}

    for pattern in patterns:
        for match in re.finditer(pattern, html):
            name = match.group(1)
            if name in target_vars:
                variables[name] = match.group(2)

    return variables


def extract_book_data_url(html: str) -> str | None:
    """Extract the book_data.php URL from the detail page.

    The URL is in the load_bookdata() function.
    """
    # Matches iframe_action2.location.href assignment to book_data.php URL
    pattern = r'window\.iframe_action2\.location\.href\s*=\s*"(/book_data\.php\?h=[^"]+)"'
    match = re.search(pattern, html)
    return match.group(1) if match else None


def parse_volume_data(html: str) -> list[Volume]:
    """Parse volume data from book_data.php response.

    The response contains postMessage calls like:
    parent.postMessage("volinfo=1001,0,0,單行本,1,卷 01,190,190,0.0,88.2,36.9,85.4,,2023-03-20,...", "*");

    Fields: vol_id, ?, ?, type, order, title, pages, ?, ?, size_mobi_mb, ?, size_epub_mb, ...
    """
    volumes: list[Volume] = []

    # Pattern for volinfo data
    pattern = r'parent\.postMessage\s*\(\s*"volinfo=([^"]+)"'

    for match in re.finditer(pattern, html):
        data = match.group(1)
        parts = data.split(",")

        if len(parts) >= 7:
            vol_id = parts[0]
            title = parts[5]
            try:
                pages = int(parts[6])
            except (ValueError, IndexError):
                pages = 1

            # Fields: [9]=size_mobi_mb, [10]=unknown, [11]=size_epub_mb
            size_mobi_mb = 0.0
            size_epub_mb = 0.0
            if len(parts) >= 12:
                with contextlib.suppress(ValueError):
                    size_mobi_mb = float(parts[9])
                with contextlib.suppress(ValueError):
                    size_epub_mb = float(parts[11])

            volumes.append(
                Volume(
                    vol_id=vol_id,
                    title=title,
                    file_count=pages,
                    size_mobi_mb=size_mobi_mb,
                    size_epub_mb=size_epub_mb,
                )
            )

    return volumes


def parse_comic_detail(html: str) -> ComicDetail:
    """Parse comic detail page HTML.

    Note: This returns basic info. Call get_comic_detail_with_volumes()
    to also fetch volume data from the separate endpoint.
    """
    tree = HTMLParser(html)

    # Extract book_id from JS variables
    js_vars = extract_js_variables(html)
    book_id = js_vars.get("bookid", "")

    # Title and author from <title> tag: "SAKAMOTO DAYS 坂本日常 : 鈴木祐鬥 [Kindle漫畫..."
    title_tag = tree.css_first("title")
    title_text = _get_text(title_tag, "")
    title = ""
    authors: list[str] = []

    if title_text:
        # Remove suffix like " [Kindle漫畫|epub漫畫] [kxx.moe]"
        title_text = re.sub(r"\s*\[.*$", "", title_text)
        # Split by " : " to separate title and author
        if " : " in title_text:
            title, author_str = title_text.split(" : ", 1)
            authors = [author_str.strip()]
        else:
            title = title_text

    # Also try to get author from page content
    author_td = tree.css_first("td.author")
    if author_td:
        author_link = author_td.css_first("a")
        if author_link:
            author_name = _get_text(author_link, "")
            if author_name and author_name not in authors:
                authors = [author_name]

    # Status from JS variable
    status = js_vars.get("bookstatus", "")

    # Extract region and language from page text
    region = ""
    language = ""
    text_content = tree.body.text() if tree.body else ""
    region_match = re.search(r"地區：(\S+)", text_content)
    if region_match:
        region = region_match.group(1)
    language_match = re.search(r"語言：(\S+)", text_content)
    if language_match:
        language = language_match.group(1)

    # Score from book_score table
    score: float | None = None
    score_font = tree.css_first("table.book_score font[style*='font-size:30px']")
    if score_font:
        score_text = _get_text(score_font, "")
        with contextlib.suppress(ValueError):
            score = float(score_text)

    # Description from div_desc_content (set via JS, so look for the JS call)
    description = ""
    desc_match = re.search(
        r'getElementById\s*\(\s*"div_desc_content"\s*\)\s*\.innerHTML\s*=\s*"([^"]*)"',
        html,
    )
    if desc_match:
        description = desc_match.group(1).replace("<br />", "\n").replace("<br/>", "\n")

    # Cover URL from img tag
    cover_url = ""
    cover_img = tree.css_first("img[src*='cover']")
    if cover_img:
        cover_url = _get_attr(cover_img, "src", "")

    meta = ComicMeta(
        book_id=book_id,
        title=title,
        authors=authors,
        status=status,
        region=region,
        language=language,
        categories=[],
        score=score,
        cover_url=cover_url,
        description=description,
    )

    # Note: volumes are loaded separately via book_data.php
    return ComicDetail(meta=meta, volumes=[])


def parse_search_results(html: str) -> SearchResponse:
    """Parse search results page HTML.

    The page renders results via JS calls to disp_divinfo().
    We extract data from these script calls.
    """
    results: list[SearchResult] = []

    # Pattern for disp_divinfo calls:
    # disp_divinfo("div_info_"+"1", "url", "cover", "border",
    #              "tag_jp", "tag_en", "tag_end", "tag_brk",
    #              "score", "title", "author", "status", "update");
    # Note: tags are displayed when the value is EMPTY (length <= 0).
    pattern = (
        r"disp_divinfo\s*\(\s*"
        r'"div_info_"\s*\+\s*"\d+"\s*,\s*'
        r'"([^"]+)"\s*,\s*'  # url
        r'"([^"]+)"\s*,\s*'  # cover
        r'"[^"]*"\s*,\s*'  # border color
        r'"([^"]*)"\s*,\s*'  # tag_jp (empty = is Japanese)
        r'"([^"]*)"\s*,\s*'  # tag_en (empty = is English)
        r'"([^"]*)"\s*,\s*'  # tag_end (empty = 完結)
        r'"([^"]*)"\s*,\s*'  # tag_brk (empty = 停更)
        r'"([^"]*)"\s*,\s*'  # score
        r'"([^"]*)"\s*,\s*'  # title (may have <b> tags)
        r'"([^"]*)"\s*,\s*'  # author
        r'"([^"]*)"\s*,\s*'  # latest volume/chapter
        r'"([^"]*)"\s*\)'  # update date
    )

    for match in re.finditer(pattern, html):
        url = match.group(1)
        cover_url = match.group(2)
        tag_jp = match.group(3)
        tag_en = match.group(4)
        tag_end = match.group(5)
        tag_brk = match.group(6)
        score_str = match.group(7)
        title = match.group(8)
        author = match.group(9)
        latest = match.group(10)
        update_date = match.group(11)

        # Parse score
        score: float | None = None
        with contextlib.suppress(ValueError):
            if score_str:
                score = float(score_str)

        # Tags are shown when the value is empty (JS: length <= 0 means display)
        # Determine status: 完結 > 停更 > 連載 (default)
        if not tag_end:
            status = "完結"
        elif not tag_brk:
            status = "停更"
        else:
            status = "連載"

        # Determine language: 日語 > 英文 > 中文 (default)
        if not tag_jp:
            language = "日語"
        elif not tag_en:
            language = "英文"
        else:
            language = "中文"

        # Extract book_id from URL like https://kxx.moe/c/18488.htm
        book_id_match = re.search(r"/c/([^/]+)\.htm", url)
        comic_id = book_id_match.group(1) if book_id_match else ""

        # Remove HTML tags from title
        title = re.sub(r"<[^>]+>", "", title)

        result = SearchResult(
            comic_id=comic_id,
            title=title,
            authors=[author] if author else [],
            cover_url=cover_url,
            last_update=f"{latest} ({update_date})" if update_date else latest,
            score=score,
            status=status,
            language=language,
        )
        results.append(result)

    # Pagination: extract total pages from disp_divpage call and current page from page_now var
    current_page = 1
    total_pages = 1 if results else 0

    page_match = re.search(
        r'disp_divpage\s*\(\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"?(\d+)"?',
        html,
    )
    if page_match:
        total_pages = int(page_match.group(1))

    # Current page from page_now variable
    page_now_match = re.search(r'var\s+page_now\s*=\s*"(\d+)"', html)
    if page_now_match:
        current_page = int(page_now_match.group(1))

    return SearchResponse(
        results=results,
        total_pages=total_pages,
        current_page=current_page,
    )


def parse_my_page_quota(html: str) -> tuple[float, float, float]:
    """Parse quota info from my.php HTML.

    Returns:
        (quota_free_month, quota_remaining, quota_extra) in MB.
    """
    quota_free_month = 0.0
    quota_remaining = 0.0
    quota_extra = 0.0

    quota_free_match = re.search(r"Lv\d+\s*每月額度\s*:\s*&nbsp;\s*([0-9.]+)\s*M", html)
    if quota_free_match:
        quota_free_month = float(quota_free_match.group(1))

    remaining_match = re.search(r"剩餘\s*:\s*&nbsp;\s*([0-9.]+)\s*M", html)
    if remaining_match:
        quota_remaining = float(remaining_match.group(1))

    extra_match = re.search(r"額外額度剩餘\s*:\s*&nbsp;\s*([0-9.]+)\s*M", html)
    if extra_match:
        quota_extra = float(extra_match.group(1))

    return (quota_free_month, quota_remaining, quota_extra)


def parse_user_status(html: str) -> UserStatus:
    """Extract user status from page JS variables."""
    js_vars = extract_js_variables(html)

    uin = js_vars.get("uin", "")
    username = uin

    level = 0
    level_str = js_vars.get("ulevel", "0")
    with contextlib.suppress(ValueError):
        level = int(level_str)

    is_vip = js_vars.get("is_vip", "0") == "1"

    quota_now = 0.0
    quota_str = js_vars.get("quota_now", "0")
    with contextlib.suppress(ValueError):
        quota_now = float(quota_str)

    # Parse detailed quota breakdown (in MB)
    quota_free_month = 0.0
    quota_free_str = js_vars.get("quota_free_month", "0")
    with contextlib.suppress(ValueError):
        quota_free_month = float(quota_free_str)

    quota_remaining = 0.0
    quota_remaining_str = js_vars.get("quota_remaining", "0")
    with contextlib.suppress(ValueError):
        quota_remaining = float(quota_remaining_str)

    quota_extra = 0.0
    quota_extra_str = js_vars.get("quota_extra", "0")
    with contextlib.suppress(ValueError):
        quota_extra = float(quota_extra_str)

    return UserStatus(
        uin=uin,
        username=username,
        level=level,
        is_vip=is_vip,
        quota_now=quota_now,
        quota_free_month=quota_free_month,
        quota_remaining=quota_remaining,
        quota_extra=quota_extra,
    )
