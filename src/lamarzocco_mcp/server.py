"""MCP server exposing pylamarzocco's cloud read methods as tools.

One tool per read method of ``LaMarzoccoCloudClient``. The server adds no logic of its own: it
calls the method, takes the raw JSON response and passes it through ``presentation.present``.

Read-only by default. Seven write tools (see ``write_tools``) are added only when
LAMARZOCCO_MCP_ALLOW_WRITE=1 is set in the server's environment.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from pylamarzocco import LaMarzoccoCloudClient

from . import __version__, write_tools
from .client import LaMarzoccoError, LaMarzoccoService
from .credentials import CredentialsMissingError, load_credentials
from .presentation import present
from .setup_cli import run_setup

service = LaMarzoccoService()

ALLOW_WRITE = os.environ.get(write_tools.ALLOW_WRITE_ENV, "").strip() == "1"

_COMMON_INSTRUCTIONS = (
    "Access to La Marzocco home espresso machines through La Marzocco's cloud "
    "(unofficial, not affiliated with La Marzocco). Times are ISO 8601 in the user's local "
    "time. Shot durations (extractionSeconds) are pump time as measured by the machine, "
    "which is usually a few seconds shorter than a scale's timer."
)
_READ_ONLY_INSTRUCTIONS = (
    " This server is read-only: it cannot turn the machine on or off or change any setting."
)
_WRITE_INSTRUCTIONS = (
    " Write tools are enabled: power, steam, steam level, coffee temperature, pre-brewing and "
    "smart standby. Only change the machine when the user explicitly asks for that change."
)


@asynccontextmanager
async def _lifespan(_: MCPServer[None]) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await service.close()


server: MCPServer[None] = MCPServer(
    name="lamarzocco",
    version=__version__,
    instructions=_COMMON_INSTRUCTIONS
    + (_WRITE_INSTRUCTIONS if ALLOW_WRITE else _READ_ONLY_INSTRUCTIONS),
    lifespan=_lifespan,
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

Serial = Annotated[
    str | None,
    Field(
        description=(
            "Machine serial number from list_machines. Leave empty to use the configured "
            "machine, or the only machine on the account."
        )
    ),
]

MAX_TREND_DAYS = 30  # the API timed out at 90 days


def local_timezone_name() -> str:
    """Best-effort IANA timezone name of this computer."""
    try:
        target = str(Path("/etc/localtime").resolve())
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


async def _fetch(call: Callable[[LaMarzoccoCloudClient], Awaitable[Any]]) -> Any:
    try:
        return await service.fetch(call)
    except LaMarzoccoError as err:
        raise ToolError(str(err)) from err


async def _serial(serial_number: str | None) -> str:
    try:
        return await service.resolve_serial(serial_number)
    except LaMarzoccoError as err:
        raise ToolError(str(err)) from err


def _widget_output(raw: Any) -> Any:
    """Extended statistics come wrapped as {"code", "index", "output"}."""
    if isinstance(raw, dict) and "output" in raw:
        return raw["output"]
    return raw


@server.tool(annotations=READ_ONLY)
async def list_machines() -> dict[str, Any]:
    """List the La Marzocco machines on the account: model, name, serial number, online state."""
    raw = await _fetch(lambda c: c.list_things())
    return {"machines": present(raw)}


@server.tool(annotations=READ_ONLY)
async def get_machine_status(serial_number: Serial = None) -> dict[str, Any]:
    """Current machine status: on or standby, coffee and steam boiler state and targets,
    pre-brewing, and back flush. From the dashboard in La Marzocco's app."""
    serial = await _serial(serial_number)
    return present(await _fetch(lambda c: c.get_thing_dashboard(serial)))  # type: ignore[no-any-return]


@server.tool(annotations=READ_ONLY)
async def get_machine_settings(serial_number: Serial = None) -> dict[str, Any]:
    """Machine settings: firmware versions, wifi signal, plumb-in, auto-update."""
    serial = await _serial(serial_number)
    return present(await _fetch(lambda c: c.get_thing_settings(serial)))  # type: ignore[no-any-return]


@server.tool(annotations=READ_ONLY)
async def get_statistics(serial_number: Serial = None) -> dict[str, Any]:
    """The statistics widgets selected in La Marzocco's app, e.g. the last coffees and the
    total coffee and flush counters."""
    serial = await _serial(serial_number)
    return present(await _fetch(lambda c: c.get_thing_statistics(serial)))  # type: ignore[no-any-return]


@server.tool(annotations=READ_ONLY)
async def get_firmware_status(serial_number: Serial = None) -> dict[str, Any]:
    """Firmware update status (whether the machine is up to date or updating)."""
    serial = await _serial(serial_number)
    return present(await _fetch(lambda c: c.get_thing_firmware(serial)))  # type: ignore[no-any-return]


@server.tool(annotations=READ_ONLY)
async def get_schedule(serial_number: Serial = None) -> dict[str, Any]:
    """Smart standby, wake-up/sleep schedules and early start settings."""
    serial = await _serial(serial_number)
    return present(await _fetch(lambda c: c.get_thing_schedule(serial)))  # type: ignore[no-any-return]


@server.tool(annotations=READ_ONLY)
async def get_coffee_and_flush_counter(serial_number: Serial = None) -> dict[str, Any]:
    """Total number of coffees and flushes the machine has made."""
    serial = await _serial(serial_number)
    raw = await _fetch(lambda c: c.get_thing_coffee_and_flush_counter(serial))
    return present(_widget_output(raw))  # type: ignore[no-any-return]


@server.tool(annotations=READ_ONLY)
async def get_last_coffees(
    serial_number: Serial = None,
    limit: Annotated[int, Field(ge=1, le=15, description="How many shots to return.")] = 15,
) -> dict[str, Any]:
    """The machine's most recent shots, newest first (La Marzocco keeps the latest 15).

    Each shot has its end time, extractionSeconds, dose mode, target temperature and whether
    La Marzocco considers it valid. extractionSeconds is pump time measured by the machine,
    not a scale timer, so it is usually a few seconds shorter than a scale shows.
    """
    serial = await _serial(serial_number)
    raw = await _fetch(lambda c: c.get_thing_last_coffee(serial, days=1))
    output = present(_widget_output(raw))
    if isinstance(output, dict) and isinstance(output.get("lastCoffees"), list):
        output["lastCoffees"] = output["lastCoffees"][:limit]
    return output  # type: ignore[no-any-return]


@server.tool(annotations=READ_ONLY)
async def get_coffee_and_flush_trend(
    serial_number: Serial = None,
    days: Annotated[
        int, Field(ge=1, le=MAX_TREND_DAYS, description="Number of days, up to 30.")
    ] = 7,
) -> dict[str, Any]:
    """Coffees and flushes per day for the last N days, in the user's local timezone."""
    serial = await _serial(serial_number)
    tz = local_timezone_name()
    raw = await _fetch(lambda c: c.get_thing_coffee_and_flush_trend(serial, days=days, timezone=tz))
    return present(_widget_output(raw))  # type: ignore[no-any-return]


if ALLOW_WRITE:
    write_tools.register(server, lambda: service)


STATE_DIR_ENV_VAR = "LAMARZOCCO_MCP_STATE_DIR"
ALLOW_REMOTE_WRITE_ENV = "LAMARZOCCO_MCP_ALLOW_REMOTE_WRITE"
APP_NAME = "La Marzocco"
REMOTE_HINT = "Remote access needs the extra: `pip install 'lamarzocco-mcp[remote]'`."


def state_dir() -> Path:
    raw = os.environ.get(STATE_DIR_ENV_VAR, "").strip()
    path = Path(raw).expanduser() if raw else Path("~/.config/lamarzocco-mcp").expanduser()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def auth_config() -> Any:
    from mcp_owner_auth import OwnerAuthConfig

    access = "read and control" if ALLOW_WRITE else "read-only access to"
    return OwnerAuthConfig.from_env(
        "LAMARZOCCO_MCP",
        state_dir=state_dir(),
        app_name=APP_NAME,
        command="lamarzocco-mcp",
        scope="lamarzocco:write" if ALLOW_WRITE else "lamarzocco:read",
        consent=f"{access} your La Marzocco espresso machine "
        "(status, settings, statistics and recent shots)",
    )


def _add_auth_parser(commands: Any) -> None:
    try:
        from mcp_owner_auth import cli as auth_cli
    except ImportError:
        stub = commands.add_parser("auth", help="manage remote-access login (needs [remote])")
        stub.add_argument("action", nargs="?")
        return
    auth_cli.add_parser(commands)


def _run_auth(args: argparse.Namespace) -> int:
    try:
        from mcp_owner_auth import cli as auth_cli
    except ImportError:
        print(REMOTE_HINT, file=sys.stderr)
        return 2
    return auth_cli.run(
        args.action,
        auth_db=state_dir() / "auth.db",
        app_name=APP_NAME,
        command="lamarzocco-mcp",
        force=args.force,
        redirect_uris=args.redirect_uri,
    )


def _serve_http(host: str, port: int) -> None:
    try:
        from mcp_owner_auth import ConfigError, serve
    except ImportError:
        print(REMOTE_HINT, file=sys.stderr)
        sys.exit(2)
    if ALLOW_WRITE and os.environ.get(ALLOW_REMOTE_WRITE_ENV, "").strip() != "1":
        print(
            f"Refusing to serve write tools remotely. Unset {write_tools.ALLOW_WRITE_ENV}, or "
            f"also set {ALLOW_REMOTE_WRITE_ENV}=1 if you really want that.",
            file=sys.stderr,
        )
        sys.exit(2)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        config = auth_config()
        load_credentials()  # fail at startup, not on the first tool call
        print(f"Serving {config.resource} on {host}:{port} ({config.auth_mode})", file=sys.stderr)
        serve(server, config, host=host, port=port)
    except (ConfigError, CredentialsMissingError, OSError, ValueError) as err:
        print(f"Cannot start: {err}", file=sys.stderr)
        sys.exit(2)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``lamarzocco-mcp`` console script.

    Without arguments it runs the MCP server over stdio (what MCP clients start). ``setup``
    stores the La Marzocco login in the keyring. ``serve --http`` serves Streamable HTTP behind
    single-user OAuth (needs the ``remote`` extra); ``auth`` manages that login.
    """
    parser = argparse.ArgumentParser(
        prog="lamarzocco-mcp",
        description="Unofficial MCP server for La Marzocco espresso machines. "
        "Run without arguments to serve MCP over stdio.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    setup = commands.add_parser("setup", help="store your La Marzocco login in the keyring")
    setup.add_argument("--delete", action="store_true", help="remove the stored login instead")
    serve = commands.add_parser("serve", help="run the MCP server (stdio unless --http)")
    serve.add_argument("--http", action="store_true", help="Streamable HTTP with OAuth")
    serve.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    _add_auth_parser(commands)
    args = parser.parse_args(argv)

    if args.command == "setup":
        sys.exit(run_setup(delete=args.delete))
    if args.command == "auth":
        sys.exit(_run_auth(args))
    if args.command == "serve" and args.http:
        _serve_http(args.host, args.port)
        return
    server.run("stdio")


if __name__ == "__main__":
    main()
