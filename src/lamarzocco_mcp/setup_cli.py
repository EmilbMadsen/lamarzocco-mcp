"""``lamarzocco-mcp setup``: store La Marzocco credentials in the system keyring.

Asks for email and password, generates and registers an installation key, verifies the login by
listing machines, and saves everything, including the chosen machine's serial number, in the
keyring. Nothing is written to disk.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
import uuid

from aiohttp import ClientSession
from pylamarzocco import LaMarzoccoCloudClient
from pylamarzocco.exceptions import AuthFail, PolicyAcceptanceRequired, RequestNotSuccessful
from pylamarzocco.util import generate_installation_key

from .credentials import (
    Credentials,
    delete_credentials,
    save_credentials,
    save_serial_number,
)


async def _setup() -> int:
    print("La Marzocco login (email + password; Google/Apple sign-in is not supported).")
    print("Your password is stored only in the system keyring.\n")
    username = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    if not username or not password:
        print("Email and password are required.", file=sys.stderr)
        return 1

    installation_key = generate_installation_key(str(uuid.uuid4()).lower())

    async with ClientSession() as session:
        client = LaMarzoccoCloudClient(
            username=username,
            password=password,
            installation_key=installation_key,
            client=session,
        )
        try:
            print("Registering this installation with La Marzocco ...")
            await client.async_register_client()
            print("Signing in and listing machines ...")
            things = await client.list_things()
        except AuthFail as err:
            print(f"Login failed: {err}", file=sys.stderr)
            return 1
        except PolicyAcceptanceRequired:
            print(
                "Accept La Marzocco's latest privacy policy in their app first.",
                file=sys.stderr,
            )
            return 1
        except RequestNotSuccessful as err:
            print(f"Request to La Marzocco failed: {err}", file=sys.stderr)
            return 1

    save_credentials(
        Credentials(username=username, password=password, installation_key=installation_key)
    )
    print("Login and installation key saved to the system keyring.")

    if not things:
        print("No machines found on this account.")
        return 0

    print("\nMachines on this account:")
    for i, thing in enumerate(things, start=1):
        print(f"  {i}. {thing.model_name} '{thing.name}' (serial {thing.serial_number})")

    choice = 1
    if len(things) > 1:
        raw = input(f"Which machine should be the default? [1-{len(things)}]: ").strip()
        choice = int(raw) if raw.isdigit() and 1 <= int(raw) <= len(things) else 1

    save_serial_number(things[choice - 1].serial_number)
    print(f"Default machine: '{things[choice - 1].name}'. Setup complete.")
    return 0


def run_setup(delete: bool = False) -> int:
    if delete:
        delete_credentials()
        print("Removed La Marzocco credentials and serial number from the keyring.")
        return 0
    try:
        return asyncio.run(_setup())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing was saved.")
        return 130
