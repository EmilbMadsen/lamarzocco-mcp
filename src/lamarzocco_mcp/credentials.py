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
import os
from dataclasses import dataclass

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


def load_credentials() -> Credentials:
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
    stored = keyring.get_password(KEYRING_SERVICE, _SERIAL)
    if stored:
        return stored
    raise CredentialsMissingError(f"No machine serial number configured. {SETUP_HINT}")
