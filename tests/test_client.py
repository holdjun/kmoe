"""Tests for kmoe.client module."""

from __future__ import annotations

import httpx
import pytest
import respx

from kmoe.client import FAILOVER_STATUS_CODES, KmoeClient
from kmoe.exceptions import MirrorExhaustedError, NetworkError, QuotaExhaustedError
from kmoe.models import AppConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(**overrides: object) -> AppConfig:
    """Build an AppConfig with fast defaults for testing."""
    defaults: dict[str, object] = {
        "rate_limit_delay": 0,
        "max_retries": 2,
        "preferred_mirror": "kxx.moe",
        "mirror_failover": True,
    }
    defaults.update(overrides)
    return AppConfig(**defaults)  # type: ignore[arg-type]


URL_TEMPLATE = "https://{domain}/test"


# ---------------------------------------------------------------------------
# Basic request
# ---------------------------------------------------------------------------


class TestBasicRequest:
    """Given a working mirror."""

    @respx.mock
    async def test_get_returns_response(self) -> None:
        """When the request succeeds, the response is returned."""
        respx.get("https://kxx.moe/test").mock(return_value=httpx.Response(200, text="ok"))
        async with KmoeClient(_config()) as client:
            resp = await client.get(URL_TEMPLATE)
        assert resp.status_code == 200
        assert resp.text == "ok"

    @respx.mock
    async def test_post_returns_response(self) -> None:
        """When a POST succeeds, the response is returned."""
        respx.post("https://kxx.moe/test").mock(return_value=httpx.Response(200, text="posted"))
        async with KmoeClient(_config()) as client:
            resp = await client.post(URL_TEMPLATE, data={"key": "val"})
        assert resp.text == "posted"


# ---------------------------------------------------------------------------
# Mirror failover
# ---------------------------------------------------------------------------


class TestMirrorFailover:
    """Given a request that fails on some mirrors."""

    @respx.mock
    @pytest.mark.parametrize("status_code", sorted(FAILOVER_STATUS_CODES))
    async def test_failover_on_server_error(self, status_code: int) -> None:
        """When the primary mirror returns 404/502/503/504,
        then the next mirror is tried."""
        respx.get("https://kxx.moe/test").mock(return_value=httpx.Response(status_code))
        respx.get("https://kzz.moe/test").mock(return_value=httpx.Response(200, text="fallback"))
        async with KmoeClient(_config()) as client:
            resp = await client.get(URL_TEMPLATE)
        assert resp.text == "fallback"

    @respx.mock
    async def test_connect_error_triggers_retry_then_failover(self) -> None:
        """When the primary mirror has connection errors,
        retries are attempted before failing over."""
        respx.get("https://kxx.moe/test").mock(side_effect=httpx.ConnectError("down"))
        respx.get("https://kzz.moe/test").mock(return_value=httpx.Response(200, text="ok"))
        async with KmoeClient(_config(max_retries=2)) as client:
            resp = await client.get(URL_TEMPLATE)
        assert resp.text == "ok"

    @respx.mock
    async def test_all_mirrors_exhausted_raises(self) -> None:
        """When all mirrors fail, MirrorExhaustedError is raised."""
        respx.get("https://kxx.moe/test").mock(return_value=httpx.Response(502))
        respx.get("https://kzz.moe/test").mock(return_value=httpx.Response(503))
        respx.get("https://koz.moe/test").mock(return_value=httpx.Response(504))
        async with KmoeClient(_config()) as client:
            with pytest.raises(MirrorExhaustedError) as exc_info:
                await client.get(URL_TEMPLATE)
        assert len(exc_info.value.mirrors_tried) == 3

    @respx.mock
    async def test_no_failover_when_disabled(self) -> None:
        """When mirror_failover is False, only the active mirror is tried."""
        respx.get("https://kxx.moe/test").mock(return_value=httpx.Response(502))
        respx.get("https://kzz.moe/test").mock(return_value=httpx.Response(200, text="ok"))
        async with KmoeClient(_config(mirror_failover=False)) as client:
            with pytest.raises(MirrorExhaustedError) as exc_info:
                await client.get(URL_TEMPLATE)
        assert exc_info.value.mirrors_tried == ["kxx.moe"]

    @respx.mock
    async def test_successful_mirror_promoted(self) -> None:
        """When a non-preferred mirror succeeds, it becomes active_mirror."""
        respx.get("https://kxx.moe/test").mock(return_value=httpx.Response(502))
        respx.get("https://kzz.moe/test").mock(return_value=httpx.Response(200, text="ok"))
        async with KmoeClient(_config()) as client:
            assert client.active_mirror == "kxx.moe"
            await client.get(URL_TEMPLATE)
            assert client.active_mirror == "kzz.moe"


# ---------------------------------------------------------------------------
# get_download_url
# ---------------------------------------------------------------------------


class TestGetDownloadUrl:
    """Given the getdownurl.php API."""

    @respx.mock
    async def test_json_success(self) -> None:
        """When the API returns JSON with code 200, the URL is extracted."""
        respx.get(url__startswith="https://kxx.moe/getdownurl.php").mock(
            return_value=httpx.Response(
                200, text='{"code": 200, "url": "https://cdn.example.com/file.epub"}'
            )
        )
        async with KmoeClient(_config()) as client:
            url = await client.get_download_url("18488", "1001", 2)
        assert url == "https://cdn.example.com/file.epub"

    @respx.mock
    async def test_plain_text_url(self) -> None:
        """When the API returns a plain text URL, it is returned directly."""
        respx.get(url__startswith="https://kxx.moe/getdownurl.php").mock(
            return_value=httpx.Response(200, text="https://cdn.example.com/file.epub")
        )
        async with KmoeClient(_config()) as client:
            url = await client.get_download_url("18488", "1001", 2)
        assert url == "https://cdn.example.com/file.epub"

    @respx.mock
    async def test_relative_url_prepends_domain(self) -> None:
        """When the API returns a relative path, the active mirror domain is prepended."""
        respx.get(url__startswith="https://kxx.moe/getdownurl.php").mock(
            return_value=httpx.Response(200, text="/dl/file.epub")
        )
        async with KmoeClient(_config()) as client:
            url = await client.get_download_url("18488", "1001", 2)
        assert url == "https://kxx.moe/dl/file.epub"

    @respx.mock
    async def test_json_error_raises(self) -> None:
        """When the API returns JSON with an error, NetworkError is raised."""
        respx.get(url__startswith="https://kxx.moe/getdownurl.php").mock(
            return_value=httpx.Response(200, text='{"error": "bad request"}')
        )
        async with KmoeClient(_config()) as client:
            with pytest.raises(NetworkError, match="bad request"):
                await client.get_download_url("18488", "1001", 2)

    @respx.mock
    async def test_quota_exhausted_raises(self) -> None:
        """When the API returns a quota error, QuotaExhaustedError is raised."""
        respx.get(url__startswith="https://kxx.moe/getdownurl.php").mock(
            return_value=httpx.Response(200, text='{"code": 500, "msg": "額度不足，請明天再試"}')
        )
        async with KmoeClient(_config()) as client:
            with pytest.raises(QuotaExhaustedError):
                await client.get_download_url("18488", "1001", 2)

    @respx.mock
    async def test_unexpected_response_raises(self) -> None:
        """When the API returns something unexpected, NetworkError is raised."""
        respx.get(url__startswith="https://kxx.moe/getdownurl.php").mock(
            return_value=httpx.Response(200, text="not-a-url-or-json")
        )
        async with KmoeClient(_config()) as client:
            with pytest.raises(NetworkError, match="Unexpected"):
                await client.get_download_url("18488", "1001", 2)


# ---------------------------------------------------------------------------
# Cookie public API
# ---------------------------------------------------------------------------


class TestCookieAPI:
    """Given the set_cookies/get_cookies public API."""

    async def test_set_and_get_cookies(self) -> None:
        """When cookies are set, get_cookies returns them."""
        async with KmoeClient(_config()) as client:
            client.set_cookies({"session_id": "abc123", "token": "xyz"})
            cookies = client.get_cookies()
        assert cookies["session_id"] == "abc123"
        assert cookies["token"] == "xyz"
