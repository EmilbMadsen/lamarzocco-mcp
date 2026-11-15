"""One-time setup: store La Marzocco credentials in the system keyring.

Asks for username and password, generates and registers an installation key, verifies the login
by listing machines, and writes the chosen machine's serial number to `.env`.

    uv run python scripts/setup_credentials.py
    uv run python scripts/setup_credentials.py --delete   # remove stored credentials
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid
from pathlib import Path

from aiohttp import ClientSession
from dotenv import set_key
from pylamarzocco import LaMarzoccoCloudClient
from pylamarzocco.exceptions import AuthFail, PolicyAcceptanceRequired, RequestNotSuccessful
from pylamarzocco.util import generate_installation_key

from lamarzocco_mcp.credentials import (
    SERIAL_ENV_VAR,
    Credentials,
    delete_credentials,
    save_credentials,
)

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


async def setup() -> int:
    print("La Marzocco login (email + password; Google/Apple sign-in is not supported).")
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
            print("Registering installation key ...")
            await client.async_register_client()
            print("Signing in and listing machines ...")
            things = await client.list_things()
        except AuthFail as err:
            print(f"Login failed: {err}", file=sys.stderr)
            return 1
        except PolicyAcceptanceRequired:
            print(
                "You must accept La Marzocco's latest privacy policy in their app first.",
                file=sys.stderr,
            )
            return 1
        except RequestNotSuccessful as err:
            print(f"Request to La Marzocco failed: {err}", file=sys.stderr)
            return 1

    save_credentials(
        Credentials(username=username, password=password, installation_key=installation_key)
    )
    print("Credentials and installation key saved to the system keyring.")

    if not things:
        print("No machines found on this account.")
        return 0

    print("\nMachines on this account:")
    for i, thing in enumerate(things, start=1):
        print(f"  {i}. {thing.model_name} '{thing.name}' (serial {thing.serial_number})")

    choice = 1
    if len(things) > 1:
        raw = input(f"Which machine should be used? [1-{len(things)}]: ").strip()
        choice = int(raw) if raw.isdigit() and 1 <= int(raw) <= len(things) else 1

    serial = things[choice - 1].serial_number
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), SERIAL_ENV_VAR, serial)
    print(f"Wrote {SERIAL_ENV_VAR} to {ENV_FILE.name}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--delete", action="store_true", help="remove stored credentials")
    args = parser.parse_args()
    if args.delete:
        delete_credentials()
        print("Removed La Marzocco credentials from the keyring.")
        return 0
    return asyncio.run(setup())


if __name__ == "__main__":
    sys.exit(main())
