"""TOML configuration management for the Kmoe manga downloader."""

import tomllib
from pathlib import Path

from kmoe.exceptions import ConfigError
from kmoe.models import AppConfig
from kmoe.utils import ensure_dir, get_data_dir


def get_config_path() -> Path:
    """Return the path to config.toml inside the data directory."""
    return get_data_dir() / "config.toml"


def load_config() -> AppConfig:
    """Load configuration from the TOML file.

    Returns a default ``AppConfig`` when the file does not exist.
    Raises ``ConfigError`` if the file exists but cannot be parsed.
    """
    path = get_config_path()

    if not path.exists():
        return AppConfig()

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    kwargs: dict[str, object] = {}

    if "download_dir" in data:
        kwargs["download_dir"] = Path(data["download_dir"]).expanduser()
    if "default_format" in data:
        kwargs["default_format"] = str(data["default_format"])
    if "preferred_mirror" in data:
        kwargs["preferred_mirror"] = str(data["preferred_mirror"])
    if "mirror_failover" in data:
        kwargs["mirror_failover"] = bool(data["mirror_failover"])
    if "rate_limit_delay" in data:
        kwargs["rate_limit_delay"] = float(data["rate_limit_delay"])
    if "max_retries" in data:
        kwargs["max_retries"] = int(data["max_retries"])
    if "preferred_language" in data:
        kwargs["preferred_language"] = str(data["preferred_language"])
    if "max_download_workers" in data:
        kwargs["max_download_workers"] = int(data["max_download_workers"])

    return AppConfig(**kwargs)  # type: ignore[arg-type]


def save_config(config: AppConfig) -> None:
    """Serialize *config* to the TOML file.

    Uses a simple manual formatter since the stdlib ``tomllib`` is read-only.
    """
    path = get_config_path()
    ensure_dir(path.parent)

    download_dir_str = str(config.download_dir)
    home = str(Path.home())
    if download_dir_str.startswith(home):
        download_dir_str = "~" + download_dir_str[len(home) :]

    lines = [
        f'download_dir = "{download_dir_str}"',
        f'default_format = "{config.default_format}"',
        f'preferred_mirror = "{config.preferred_mirror}"',
        f"mirror_failover = {str(config.mirror_failover).lower()}",
        f"rate_limit_delay = {config.rate_limit_delay}",
        f"max_retries = {config.max_retries}",
        f'preferred_language = "{config.preferred_language}"',
        f"max_download_workers = {config.max_download_workers}",
    ]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_or_create_config() -> AppConfig:
    """Load config from disk, creating a default file when none exists."""
    path = get_config_path()

    if not path.exists():
        config = AppConfig()
        save_config(config)
        return config

    return load_config()
