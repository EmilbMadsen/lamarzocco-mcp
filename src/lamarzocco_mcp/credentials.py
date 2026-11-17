"""Credential storage in the system keyring.

Username, password and the installation key are stored only in the keyring. They must never be
written to code, `.env` or git.

The machine serial number is not secret. ``lamarzocco-mcp setup`` stores it in the keyring too,
so an installed package needs no files. ``LAMARZOCCO_SERIAL`` (environment or a `.env` in the
working directory) overrides it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
from dotenv import find_dotenv, load_dotenv
from keyring.errors import PasswordDeleteError
from pylamarzocco.util import InstallationKey

KEYRING_SERVICE = "lamarzocco-mcp"
_USERNAME = "username"
_PASSWORD = "password"
_INSTALLATION_KEY = "installation_key"
_SERIAL = "serial_number"

SERIAL_ENV_VAR = "LAMARZOCCO_SERIAL"
# For servers and containers without a keyring: a JSON file (e.g. a Docker secret) with
# {"username", "password", "installation_key": {...}, "serial_number" (optional)}.
CREDENTIALS_FILE_ENV_VAR = "LAMARZOCCO_CREDENTIALS_FILE"
_LOGGER = logging.getLogger(__name__)

SETUP_HINT = "Run `uvx lamarzocco-mcp setup` (or `uv run lamarzocco-mcp setup` in a checkout)."


class CredentialsMissingError(RuntimeError):
    """Raised when credentials have not been set up yet."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    installation_key: InstallationKey


def save_credentials(credentials: Credentials) -> None:
    keyring.set_password(KEYRING_SERVICE, _USERNAME, credentials.username)
    keyring.set_password(KEYRING_SERVICE, _PASSWORD, credentials.password)
    keyring.set_password(
        KEYRING_SERVICE, _INSTALLATION_KEY, json.dumps(credentials.installation_key.to_dict())
    )


def _credentials_file() -> dict[str, Any] | None:
    raw = os.environ.get(CREDENTIALS_FILE_ENV_VAR, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CredentialsMissingError(
            f"{CREDENTIALS_FILE_ENV_VAR} points to {path}, which is not a readable JSON file."
        ) from exc
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        _LOGGER.warning("%s is readable by other users; restrict it with chmod 600", path)
    if not isinstance(data, dict):
        raise CredentialsMissingError(f"{path} must contain a JSON object.")
    return data


def load_credentials() -> Credentials:
    from_file = _credentials_file()
    if from_file is not None:
        try:
            return Credentials(
                username=str(from_file["username"]),
                password=str(from_file["password"]),
                installation_key=InstallationKey.from_dict(from_file["installation_key"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CredentialsMissingError(
                f"The credentials file needs username, password and installation_key. {SETUP_HINT}"
            ) from exc
    username = keyring.get_password(KEYRING_SERVICE, _USERNAME)
    password = keyring.get_password(KEYRING_SERVICE, _PASSWORD)
    key_json = keyring.get_password(KEYRING_SERVICE, _INSTALLATION_KEY)
    if not (username and password and key_json):
        raise CredentialsMissingError(f"No La Marzocco credentials in the keyring. {SETUP_HINT}")
    return Credentials(
        username=username,
        password=password,
        installation_key=InstallationKey.from_dict(json.loads(key_json)),
    )


def save_serial_number(serial: str) -> None:
    keyring.set_password(KEYRING_SERVICE, _SERIAL, serial)


def delete_credentials() -> None:
    for name in (_USERNAME, _PASSWORD, _INSTALLATION_KEY, _SERIAL):
        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, name)


def load_serial_number() -> str:
    """LAMARZOCCO_SERIAL from the environment or a .env in the working directory, else the
    serial saved by setup."""
    load_dotenv(find_dotenv(usecwd=True))
    serial = os.environ.get(SERIAL_ENV_VAR, "").strip()
    if serial:
        return serial
    from_file = _credentials_file()
    if from_file is not None and from_file.get("serial_number"):
        return str(from_file["serial_number"])
    stored = keyring.get_password(KEYRING_SERVICE, _SERIAL)
    if stored:
        return stored
    raise CredentialsMissingError(f"No machine serial number configured. {SETUP_HINT}")
