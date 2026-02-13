"""Tests for kmoe.auth module."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest

from kmoe.auth import load_session, save_session

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def _session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect session storage to a temporary directory."""
    session_path = tmp_path / "session.enc"
    monkeypatch.setattr("kmoe.auth._get_session_path", lambda: session_path)


@pytest.mark.usefixtures("_session_dir")
def test_save_and_load_roundtrip() -> None:
    """Cookies survive a save -> load roundtrip."""
    cookies = {"session_id": "abc123", "token": "xyz789"}
    save_session(cookies)
    assert load_session() == cookies


@pytest.mark.usefixtures("_session_dir")
def test_load_missing_file() -> None:
    """Returns None when session file does not exist."""
    assert load_session() is None


@pytest.mark.usefixtures("_session_dir")
def test_load_corrupted_file(tmp_path: Path) -> None:
    """Returns None when session file contains garbage."""
    (tmp_path / "session.enc").write_bytes(b"not-valid-fernet-data")
    assert load_session() is None


@pytest.mark.usefixtures("_session_dir")
def test_load_wrong_machine_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when machine identity changes after save."""
    save_session({"session_id": "abc123"})

    # Simulate a different machine by swapping the key
    wrong_key = base64.urlsafe_b64encode(b"\x00" * 32)
    monkeypatch.setattr("kmoe.auth._get_machine_key", lambda: wrong_key)

    assert load_session() is None
