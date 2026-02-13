"""Async HTTP client with mirror failover for the Kmoe manga downloader."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import anyio
import httpx

from kmoe.constants import DEFAULT_HEADERS, MIRROR_DOMAINS
from kmoe.exceptions import MirrorExhaustedError, NetworkError, QuotaExhaustedError
from kmoe.models import AppConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import TracebackType


# HTTP status codes that trigger mirror failover
# 404 is included because different mirrors may have different resource availability
FAILOVER_STATUS_CODES = frozenset({404, 502, 503, 504})


class KmoeClient:
    """Async HTTP client with automatic mirror failover.

    This client manages requests to Kmoe mirrors, automatically failing over
    to alternative mirrors when connection errors or server errors occur.
    It also handles rate limiting between requests.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        """Initialize the client.

        Args:
            config: Application configuration. Uses defaults if None.
        """
        self._config = config or AppConfig()
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
        )
        self._last_request_time: float = 0.0

        # Build ordered mirror list: preferred first, then others
        self._mirrors = self._build_mirror_list()
        self.active_mirror = self._mirrors[0]

    def _build_mirror_list(self) -> list[str]:
        """Build ordered list of mirrors with preferred first."""
        preferred = self._config.preferred_mirror
        mirrors = [preferred]
        for domain in MIRROR_DOMAINS:
            if domain != preferred:
                mirrors.append(domain)
        return mirrors

    def set_cookies(self, cookies: dict[str, str]) -> None:
        """Set cookies on the underlying HTTP client."""
        for name, value in cookies.items():
            self._client.cookies.set(name, value)

    def get_cookies(self) -> dict[str, str]:
        """Return current cookies as a plain dict."""
        return dict(self._client.cookies.items())

    async def _rate_limit(self) -> None:
        """Enforce rate limiting by sleeping if needed since last request."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        delay = self._config.rate_limit_delay

        if elapsed < delay and self._last_request_time > 0:
            await anyio.sleep(delay - elapsed)

        self._last_request_time = time.monotonic()

    async def get(self, url_template: str, **kwargs: str) -> httpx.Response:
        """Make a GET request with mirror failover.

        Args:
            url_template: URL template string with {domain} placeholder.
            **kwargs: Additional format parameters for the URL template.

        Returns:
            The HTTP response from a successful request.

        Raises:
            MirrorExhaustedError: When all mirrors have been tried and failed.
            NetworkError: When a non-recoverable network error occurs.
        """
        return await self._request_with_failover("GET", url_template, **kwargs)  # type: ignore[arg-type]

    async def post(
        self, url_template: str, data: dict[str, str] | None = None, **kwargs: str
    ) -> httpx.Response:
        """Make a POST request with mirror failover.

        Args:
            url_template: URL template string with {domain} placeholder.
            data: Form data to send with the request.
            **kwargs: Additional format parameters for the URL template.

        Returns:
            The HTTP response from a successful request.

        Raises:
            MirrorExhaustedError: When all mirrors have been tried and failed.
            NetworkError: When a non-recoverable network error occurs.
        """
        return await self._request_with_failover("POST", url_template, data=data, **kwargs)

    async def _request_with_failover(
        self,
        method: str,
        url_template: str,
        data: dict[str, str] | None = None,
        **kwargs: str,
    ) -> httpx.Response:
        """Execute a request with mirror failover logic.

        Args:
            method: HTTP method (GET or POST).
            url_template: URL template with {domain} placeholder.
            data: Form data for POST requests.
            **kwargs: Additional URL template parameters.

        Returns:
            Successful HTTP response.

        Raises:
            MirrorExhaustedError: All mirrors failed.
        """
        if not self._config.mirror_failover:
            # No failover: just try the active mirror
            mirrors_to_try = [self.active_mirror]
        else:
            # Build mirror list starting from active mirror
            mirrors_to_try = [self.active_mirror]
            for m in self._mirrors:
                if m != self.active_mirror:
                    mirrors_to_try.append(m)

        errors: list[tuple[str, Exception]] = []

        for mirror in mirrors_to_try:
            url = url_template.format(domain=mirror, **kwargs)

            for attempt in range(self._config.max_retries):
                try:
                    await self._rate_limit()

                    if method == "GET":
                        response = await self._client.get(url)
                    else:
                        response = await self._client.post(url, data=data)

                    # Check for server error status codes that warrant failover
                    if response.status_code in FAILOVER_STATUS_CODES:
                        errors.append(
                            (mirror, NetworkError(f"Server returned {response.status_code}"))
                        )
                        break  # Try next mirror

                    # Success! Promote this mirror if it's different from active
                    if mirror != self.active_mirror:
                        self.active_mirror = mirror

                    return response

                except httpx.ConnectError as exc:
                    errors.append((mirror, exc))
                    # Exponential backoff before retry
                    if attempt < self._config.max_retries - 1:
                        backoff = (2**attempt) * 0.5
                        await anyio.sleep(backoff)
                    continue

                except httpx.RequestError as exc:
                    errors.append((mirror, exc))
                    break  # Try next mirror

            # If we get here, all retries for this mirror failed
            continue

        # All mirrors exhausted
        mirrors_tried = list(dict.fromkeys(e[0] for e in errors))
        raise MirrorExhaustedError(
            mirrors_tried=mirrors_tried,
            message=f"All mirrors exhausted: {mirrors_tried}",
        )

    async def get_download_url(
        self,
        book_id: str,
        vol_id: str,
        fmt: int,
        line: int = 0,
    ) -> str:
        """Get the real download URL from the getdownurl.php API.

        Args:
            book_id: The comic's book ID.
            vol_id: The volume ID to download.
            fmt: The format code (1=MOBI, 2=EPUB).
            line: Download server line number (0=VIP線1, 1=VIP線2).

        Returns:
            The CDN download URL with signature.

        Raises:
            MirrorExhaustedError: When all mirrors have been tried and failed.
            NetworkError: When the API returns an error.
        """
        url_template = (
            "https://{domain}/getdownurl.php?b={book_id}&v={vol_id}&mobi={fmt}&vip={line}&json=1"
        )
        response = await self._request_with_failover(
            "GET",
            url_template,
            book_id=book_id,
            vol_id=vol_id,
            fmt=str(fmt),
            line=str(line),
        )

        # The API returns the URL directly as text (or JSON with url field)
        text = response.text.strip()

        # Handle JSON response format
        if text.startswith("{"):
            import json

            data = json.loads(text)
            if "error" in data:
                raise NetworkError(f"Download API error: {data['error']}")
            # API returns code=200 for success, code=500 for error
            code = data.get("code", 0)
            if code != 200:
                msg = data.get("msg", "Unknown error")
                if "額度不足" in msg:
                    raise QuotaExhaustedError(msg)
                raise NetworkError(f"Download API error (code {code}): {msg}")
            url = data.get("url")
            if not url:
                raise NetworkError(f"Download API returned empty URL: {text[:100]}")
        else:
            url = text

        # Plain text URL response or relative path
        if url.startswith("http"):
            return url

        # Handle relative URLs by prepending the domain
        if url.startswith("/"):
            return f"https://{self.active_mirror}{url}"

        raise NetworkError(f"Unexpected download API response: {text[:100]}")

    async def download_file(
        self,
        url: str,
        dest: Path,
        progress_callback: Callable[[int], None] | None = None,
        total_callback: Callable[[int], None] | None = None,
    ) -> Path:
        """Stream download a file to the destination path.

        Args:
            url: Direct URL to download.
            dest: Destination path for the downloaded file.
            progress_callback: Optional callback called with chunk size for each chunk.
            total_callback: Optional callback called once with the total size in bytes
                (from Content-Length header) before streaming begins.

        Returns:
            The destination path.

        Raises:
            NetworkError: When the download fails.
        """
        await self._rate_limit()

        try:
            async with self._client.stream("GET", url) as response:
                response.raise_for_status()

                if total_callback is not None:
                    total = int(response.headers.get("content-length", 0))
                    if total > 0:
                        total_callback(total)

                dest.parent.mkdir(parents=True, exist_ok=True)

                with dest.open("wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        if progress_callback is not None:
                            progress_callback(len(chunk))

        except httpx.HTTPStatusError as exc:
            raise NetworkError(f"Download failed with status {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Download failed: {exc}") from exc

        return dest

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> KmoeClient:
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context manager and close the client."""
        await self.close()
