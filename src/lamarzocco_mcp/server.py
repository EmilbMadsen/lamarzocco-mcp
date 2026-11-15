"""MCP server exposing pylamarzocco's cloud read methods as tools.

One tool per read method of ``LaMarzoccoCloudClient``. The server adds no logic of its own: it
calls the method, takes the raw JSON response and passes it through ``presentation.present``.

Read-only. pylamarzocco can also control the machine (power, steam, temperatures), but none of
that is exposed here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from pylamarzocco import LaMarzoccoCloudClient

from .client import LaMarzoccoError, LaMarzoccoService
from .presentation import present

service = LaMarzoccoService()


@asynccontextmanager
async def _lifespan(_: MCPServer[None]) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await service.close()


server: MCPServer[None] = MCPServer(
    name="lamarzocco",
    version="0.1.0",
    instructions=(
        "Read-only access to La Marzocco home espresso machines through La Marzocco's cloud "
        "(unofficial, not affiliated with La Marzocco). Times are ISO 8601 in the user's local "
        "time. Shot durations (extractionSeconds) are pump time as measured by the machine, "
        "which is usually a few seconds shorter than a scale's timer. The server cannot turn "
        "the machine on or off or change any setting."
    ),
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


def main() -> None:
    """Entry point for the ``lamarzocco-mcp`` console script."""
    server.run("stdio")


if __name__ == "__main__":
    main()
