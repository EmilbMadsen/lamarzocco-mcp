"""Credential storage in the system keyring.

Username, password and the installation key are stored only in the keyring. They must never be
written to code, `.env` or git. The machine serial number is not secret and lives in `.env`.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass

import keyring
from dotenv import load_dotenv
from keyring.errors import PasswordDeleteError
from pylamarzocco.util import InstallationKey

KEYRING_SERVICE = "lamarzocco-mcp"
_USERNAME = "username"
_PASSWORD = "password"
_INSTALLATION_KEY = "installation_key"

SERIAL_ENV_VAR = "LAMARZOCCO_SERIAL"


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


def load_credentials() -> Credentials:
    username = keyring.get_password(KEYRING_SERVICE, _USERNAME)
    password = keyring.get_password(KEYRING_SERVICE, _PASSWORD)
    key_json = keyring.get_password(KEYRING_SERVICE, _INSTALLATION_KEY)
    if not (username and password and key_json):
        raise CredentialsMissingError(
            "No La Marzocco credentials in the keyring. "
            "Run `uv run python scripts/setup_credentials.py` first."
        )
    return Credentials(
        username=username,
        password=password,
        installation_key=InstallationKey.from_dict(json.loads(key_json)),
    )


def delete_credentials() -> None:
    for name in (_USERNAME, _PASSWORD, _INSTALLATION_KEY):
        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, name)


def load_serial_number() -> str:
    load_dotenv()
    serial = os.environ.get(SERIAL_ENV_VAR, "").strip()
    if not serial:
        raise CredentialsMissingError(
            f"{SERIAL_ENV_VAR} is not set. Add it to .env (see .env.example)."
        )
    return serial
