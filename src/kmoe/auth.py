"""Authentication module with encrypted session persistence for the Kmoe manga downloader."""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import platform
import re
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

from kmoe.constants import URLTemplate
from kmoe.exceptions import AuthError, LoginRequiredError
from kmoe.models import UserStatus
from kmoe.parser import parse_my_page_quota
from kmoe.utils import get_data_dir

if TYPE_CHECKING:
    from pathlib import Path

    from kmoe.client import KmoeClient


def _get_machine_key() -> bytes:
    """Derive a Fernet encryption key from machine-specific data."""
    base_material = f"{platform.node()}{getpass.getuser()}"
    hash_digest = hashlib.sha256(base_material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(hash_digest)


def _get_session_path() -> Path:
    """Return path to session.enc in the data directory."""
    return get_data_dir() / "session.enc"


def save_session(cookies: dict[str, str]) -> None:
    """Serialize and encrypt cookies, then write to session.enc."""
    session_path = _get_session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)

    fernet = Fernet(_get_machine_key())
    json_data = json.dumps(cookies, ensure_ascii=False)
    session_path.write_bytes(fernet.encrypt(json_data.encode("utf-8")))


def load_session() -> dict[str, str] | None:
    """Load and decrypt session cookies from session.enc."""
    session_path = _get_session_path()
    if not session_path.exists():
        return None

    try:
        fernet = Fernet(_get_machine_key())
        decrypted = fernet.decrypt(session_path.read_bytes())
        return json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, json.JSONDecodeError, ValueError):
        return None


async def _build_user_status(client: KmoeClient, home_html: str) -> UserStatus:
    """Parse user info from home page HTML and fetch quota from my.php."""
    level_match = re.search(r"Lv(\d+)", home_html)
    level = int(level_match.group(1)) if level_match else 0

    uin_match = re.search(r"/u/(\d+)/", home_html)
    uin = uin_match.group(1) if uin_match else ""

    is_vip = "VIP会员" in home_html or "VIP會員" in home_html

    quota_free_month = 0.0
    quota_remaining = 0.0
    quota_extra = 0.0
    try:
        my_response = await client.get(URLTemplate.MY)
        quota_free_month, quota_remaining, quota_extra = parse_my_page_quota(my_response.text)
    except Exception:
        pass

    return UserStatus(
        uin=uin,
        username=uin,
        level=level,
        is_vip=is_vip,
        quota_now=0.0,
        quota_free_month=quota_free_month,
        quota_remaining=quota_remaining,
        quota_extra=quota_extra,
    )


async def login(client: KmoeClient, username: str, password: str) -> UserStatus:
    """Authenticate with the Kmoe service.

    Raises:
        AuthError: If authentication fails.
    """
    form_data = {
        "email": username,
        "passwd": password,
        "keepalive": "on",
    }

    await client.post(URLTemplate.LOGIN, data=form_data)
    cookies = dict(client._client.cookies.items())

    home_response = await client.get(URLTemplate.HOME)
    home_html = home_response.text

    if "login.php" in home_html and "my.php" not in home_html:
        raise AuthError("Login failed: invalid credentials or server error")

    save_session(cookies)
    return await _build_user_status(client, home_html)


async def check_session(client: KmoeClient) -> UserStatus | None:
    """Check if saved session is still valid.

    Returns:
        UserStatus if the session is valid, None if expired or missing.
    """
    cookies = load_session()
    if cookies is None:
        return None

    for name, value in cookies.items():
        client._client.cookies.set(name, value)

    response = await client.get(URLTemplate.HOME)
    html = response.text

    if "my.php" not in html:
        return None

    return await _build_user_status(client, html)


async def ensure_logged_in(client: KmoeClient) -> UserStatus:
    """Ensure the user is logged in, raising LoginRequiredError if not."""
    status = await check_session(client)
    if status is None:
        raise LoginRequiredError()
    return status
