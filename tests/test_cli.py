"""Tests for kmoe.cli module."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from kmoe.cli import app
from kmoe.models import (
    AppConfig,
    ComicDetail,
    ComicMeta,
    DownloadedVolume,
    LibraryEntry,
    UserStatus,
    Volume,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_status(**overrides: object) -> UserStatus:
    defaults: dict[str, object] = {
        "uin": "user123",
        "username": "testuser",
        "level": 5,
        "is_vip": True,
        "quota_now": 0.0,
        "quota_free_month": 3072.0,
        "quota_remaining": 1487.5,
        "quota_extra": 0.0,
    }
    defaults.update(overrides)
    return UserStatus(**defaults)  # type: ignore[arg-type]


def _config() -> AppConfig:
    return AppConfig(download_dir=Path("/tmp/test-kmoe"))


def _mock_client_ctx(mock_client_cls: AsyncMock) -> None:
    """Set up a mock KmoeClient as an async context manager."""
    instance = AsyncMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=instance)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@patch("kmoe.cli.get_or_create_config", return_value=_config())
@patch("kmoe.cli.KmoeClient")
@patch("kmoe.cli.login", new_callable=AsyncMock, return_value=_user_status())
@patch("kmoe.cli._configure_interactively")
def test_login_success(
    _mock_config_interactive: AsyncMock,
    _mock_login: AsyncMock,
    mock_client_cls: AsyncMock,
    _mock_config: object,
) -> None:
    """Given a valid username and password,
    when login is successful,
    then user info is displayed and interactive configuration is called."""
    _mock_client_ctx(mock_client_cls)

    result = runner.invoke(app, ["login", "-u", "testuser", "-p", "secret"])

    assert result.exit_code == 0
    assert "testuser" in result.output
    assert "Login Successful" in result.output
    _mock_login.assert_awaited_once()
    _mock_config_interactive.assert_called_once()


@patch("kmoe.cli.get_or_create_config", return_value=_config())
@patch("kmoe.cli.KmoeClient")
@patch("kmoe.cli.login", new_callable=AsyncMock)
def test_login_failure(
    mock_login: AsyncMock,
    mock_client_cls: AsyncMock,
    _mock_config: object,
) -> None:
    """Given invalid credentials,
    when login fails,
    then error message is displayed and exit code is 1."""
    from kmoe.exceptions import AuthError

    mock_login.side_effect = AuthError("Login failed: invalid credentials")
    _mock_client_ctx(mock_client_cls)

    result = runner.invoke(app, ["login", "-u", "bad", "-p", "wrong"])

    assert result.exit_code == 1
    assert "Login failed" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@patch("kmoe.cli.get_or_create_config", return_value=_config())
@patch("kmoe.cli.KmoeClient")
@patch("kmoe.cli.check_session", new_callable=AsyncMock, return_value=_user_status())
def test_status_logged_in(
    _mock_check: AsyncMock,
    mock_client_cls: AsyncMock,
    _mock_config: object,
) -> None:
    """Given a valid session,
    when status command runs,
    then user info and configuration are displayed."""
    _mock_client_ctx(mock_client_cls)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "testuser" in result.output
    assert "Session Status" in result.output
    assert "Configuration" in result.output
    assert "1487.5 / 3072.0 MB" in result.output
    assert "Download Dir" in result.output
    assert "Default Format" in result.output
    assert "Preferred Mirror" in result.output
    assert "Preferred Language" in result.output


@patch("kmoe.cli.get_or_create_config", return_value=_config())
@patch("kmoe.cli.KmoeClient")
@patch("kmoe.cli.check_session", new_callable=AsyncMock, return_value=None)
def test_status_not_logged_in(
    _mock_check: AsyncMock,
    mock_client_cls: AsyncMock,
    _mock_config: object,
) -> None:
    """Given no valid session,
    when status command runs,
    then 'Not logged in' message is displayed."""
    _mock_client_ctx(mock_client_cls)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Not logged in" in result.output
    assert "Configuration" in result.output


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def _make_detail(
    volumes: list[Volume] | None = None,
    book_id: str = "18488",
    comic_id: str = "abc123",
) -> ComicDetail:
    meta = ComicMeta(book_id=book_id, comic_id=comic_id, title="Test Comic")
    return ComicDetail(meta=meta, volumes=volumes or [])


def _make_entry(
    downloaded_vol_ids: list[str] | None = None,
    book_id: str = "18488",
    comic_id: str = "abc123",
) -> LibraryEntry:
    meta = ComicMeta(book_id=book_id, comic_id=comic_id, title="Test Comic")
    downloaded = [
        DownloadedVolume(
            vol_id=vid,
            title=f"Vol {vid}",
            format="epub",
            filename=f"[Kmoe][Test Comic]Vol {vid}.epub",
            downloaded_at=datetime.now(timezone.utc),
            size_bytes=1024,
        )
        for vid in (downloaded_vol_ids or [])
    ]
    return LibraryEntry(
        book_id=book_id,
        comic_id=comic_id,
        title="Test Comic",
        meta=meta,
        downloaded_volumes=downloaded,
        total_volumes=len(downloaded),
    )


def test_update_no_args() -> None:
    """When neither comic_id nor --all is provided, exit with error."""
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "--all" in result.output


@patch("kmoe.cli.get_or_create_config", return_value=_config())
@patch("kmoe.cli.list_library", return_value=[])
def test_update_empty_library(
    _mock_list: object,
    _mock_config: object,
) -> None:
    """When library is empty, show message and return."""
    result = runner.invoke(app, ["update", "--all"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower()


@patch("kmoe.cli.save_entry")
@patch(
    "kmoe.cli.get_comic_detail",
    new_callable=AsyncMock,
    return_value=_make_detail(
        volumes=[Volume(vol_id="1001", title="Vol 01"), Volume(vol_id="1002", title="Vol 02")]
    ),
)
@patch("kmoe.cli.list_library")
@patch("kmoe.cli.get_or_create_config", return_value=_config())
@patch("kmoe.cli.KmoeClient")
@patch("kmoe.cli._apply_session")
def test_update_dry_run_shows_missing(
    _mock_session: object,
    mock_client_cls: AsyncMock,
    _mock_config: object,
    mock_list: object,
    _mock_detail: object,
    _mock_save: object,
) -> None:
    """Dry run shows available updates without downloading."""
    _mock_client_ctx(mock_client_cls)
    # Entry has vol 1001 but not 1002
    mock_list.return_value = [_make_entry(downloaded_vol_ids=["1001"])]

    result = runner.invoke(app, ["update", "--all", "--dry-run"])
    assert result.exit_code == 0
    assert "1" in result.output  # 1 new volume
    assert "Dry run" in result.output


@patch("kmoe.cli.save_entry")
@patch("kmoe.cli.find_missing_vol_ids", return_value=[])
@patch(
    "kmoe.cli.get_comic_detail",
    new_callable=AsyncMock,
    return_value=_make_detail(volumes=[Volume(vol_id="1001", title="Vol 01")]),
)
@patch("kmoe.cli.list_library")
@patch("kmoe.cli.get_or_create_config", return_value=_config())
@patch("kmoe.cli.KmoeClient")
@patch("kmoe.cli._apply_session")
def test_update_all_up_to_date(
    _mock_session: object,
    mock_client_cls: AsyncMock,
    _mock_config: object,
    mock_list: object,
    _mock_detail: object,
    _mock_stale: object,
    _mock_save: object,
) -> None:
    """When all volumes are downloaded, shows up to date."""
    _mock_client_ctx(mock_client_cls)
    mock_list.return_value = [_make_entry(downloaded_vol_ids=["1001"])]

    result = runner.invoke(app, ["update", "--all", "--dry-run"])
    assert result.exit_code == 0
    assert "up to date" in result.output.lower()
