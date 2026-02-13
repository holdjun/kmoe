"""Tests for kmoe.config module."""

from __future__ import annotations

from pathlib import Path

import pytest

from kmoe.config import get_or_create_config, load_config, save_config
from kmoe.exceptions import ConfigError
from kmoe.models import AppConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def _config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config storage to a temporary directory."""
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr("kmoe.config.get_config_path", lambda: config_path)
    return config_path


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """Given the config.toml file."""

    def test_missing_file_returns_defaults(self, _config_dir: Path) -> None:
        """When config.toml does not exist, default AppConfig is returned."""
        config = load_config()
        assert config.default_format == "epub"
        assert config.preferred_mirror == "kxx.moe"

    def test_corrupted_toml_raises_config_error(self, _config_dir: Path, tmp_path: Path) -> None:
        """When config.toml contains invalid TOML, ConfigError is raised."""
        (tmp_path / "config.toml").write_text("{{{{invalid", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config()

    def test_loads_all_fields(self, _config_dir: Path, tmp_path: Path) -> None:
        """When config.toml has all fields, they are parsed correctly."""
        toml = (
            'download_dir = "~/my-manga"\n'
            'default_format = "mobi"\n'
            'preferred_mirror = "kzz.moe"\n'
            "mirror_failover = false\n"
            "rate_limit_delay = 2.0\n"
            "max_retries = 5\n"
            'preferred_language = "jp"\n'
            "max_download_workers = 4\n"
        )
        (tmp_path / "config.toml").write_text(toml, encoding="utf-8")
        config = load_config()
        assert config.download_dir == Path("~/my-manga").expanduser()
        assert config.default_format == "mobi"
        assert config.preferred_mirror == "kzz.moe"
        assert config.mirror_failover is False
        assert config.rate_limit_delay == 2.0
        assert config.max_retries == 5
        assert config.preferred_language == "jp"
        assert config.max_download_workers == 4


# ---------------------------------------------------------------------------
# save_config + load_config roundtrip
# ---------------------------------------------------------------------------


class TestSaveConfig:
    """Given an AppConfig to persist."""

    def test_roundtrip(self, _config_dir: Path) -> None:
        """When config is saved then loaded, all values match."""
        original = AppConfig(
            download_dir=Path.home() / "test-library",
            default_format="mobi",
            preferred_mirror="koz.moe",
            mirror_failover=False,
            rate_limit_delay=0.5,
            max_retries=5,
            preferred_language="jp",
            max_download_workers=4,
        )
        save_config(original)
        loaded = load_config()

        assert loaded.download_dir == original.download_dir
        assert loaded.default_format == original.default_format
        assert loaded.preferred_mirror == original.preferred_mirror
        assert loaded.mirror_failover == original.mirror_failover
        assert loaded.rate_limit_delay == original.rate_limit_delay
        assert loaded.max_retries == original.max_retries
        assert loaded.preferred_language == original.preferred_language
        assert loaded.max_download_workers == original.max_download_workers

    def test_tilde_expansion_in_download_dir(self, _config_dir: Path) -> None:
        """When download_dir is under home, it is stored with ~ prefix."""
        config = AppConfig(download_dir=Path.home() / "manga")
        save_config(config)
        loaded = load_config()
        assert loaded.download_dir == Path.home() / "manga"


# ---------------------------------------------------------------------------
# get_or_create_config
# ---------------------------------------------------------------------------


class TestGetOrCreateConfig:
    """Given no existing config file."""

    def test_creates_file_on_first_call(self, _config_dir: Path, tmp_path: Path) -> None:
        """When called for the first time, a config.toml is created."""
        config_path = tmp_path / "config.toml"
        assert not config_path.exists()
        config = get_or_create_config()
        assert config_path.exists()
        assert config.default_format == "epub"

    def test_loads_existing_file(self, _config_dir: Path, tmp_path: Path) -> None:
        """When config.toml already exists, it is loaded (not overwritten)."""
        toml = 'default_format = "mobi"\n'
        (tmp_path / "config.toml").write_text(toml, encoding="utf-8")
        config = get_or_create_config()
        assert config.default_format == "mobi"
