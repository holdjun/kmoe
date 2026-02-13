"""Exception hierarchy for kmoe manga downloader."""


class KmoeError(Exception):
    """Base exception for all kmoe errors."""

    def __init__(self, message: str = "An unexpected kmoe error occurred"):
        self.message = message
        super().__init__(message)


# --- Authentication ---


class AuthError(KmoeError):
    """Authentication related errors."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class LoginRequiredError(AuthError):
    """User needs to login first."""

    def __init__(self, message: str = "Login required to perform this operation"):
        super().__init__(message)


class SessionExpiredError(AuthError):
    """Session has expired."""

    def __init__(self, message: str = "Session has expired, please login again"):
        super().__init__(message)


# --- Network ---


class NetworkError(KmoeError):
    """Network/HTTP related errors."""

    def __init__(self, message: str = "A network error occurred"):
        super().__init__(message)


class MirrorExhaustedError(NetworkError):
    """All mirrors have been tried and failed."""

    def __init__(
        self,
        mirrors_tried: list[str] | None = None,
        message: str = "All mirrors have been exhausted",
    ):
        self.mirrors_tried = mirrors_tried or []
        super().__init__(message)


class RateLimitError(NetworkError):
    """Rate limited by server."""

    def __init__(self, message: str = "Rate limited by server"):
        super().__init__(message)


# --- Parsing ---


class ParseError(KmoeError):
    """HTML parsing errors."""

    def __init__(self, message: str = "Failed to parse page", url: str | None = None):
        self.url = url
        if url:
            message = f"{message}: {url}"
        super().__init__(message)


# --- Download ---


class DownloadError(KmoeError):
    """Download related errors."""

    def __init__(self, message: str = "Download failed"):
        super().__init__(message)


class QuotaExhaustedError(DownloadError):
    """Download quota exhausted."""

    def __init__(self, message: str = "Download quota exhausted"):
        super().__init__(message)


# --- Not Found ---


class ComicNotFoundError(KmoeError):
    """Comic ID not found."""

    def __init__(self, comic_id: str, message: str | None = None):
        self.comic_id = comic_id
        super().__init__(message or f"Comic not found: {comic_id}")


class VolumeNotFoundError(KmoeError):
    """Volume not found."""

    def __init__(self, vol_id: str, message: str | None = None):
        self.vol_id = vol_id
        super().__init__(message or f"Volume not found: {vol_id}")


# --- Configuration ---


class ConfigError(KmoeError):
    """Configuration errors."""

    def __init__(self, message: str = "Invalid configuration"):
        super().__init__(message)
