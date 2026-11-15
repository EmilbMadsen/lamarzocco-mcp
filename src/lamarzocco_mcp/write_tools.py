"""Optional write tools: seven settings the user can change from Claude.

Registered only when LAMARZOCCO_MCP_ALLOW_WRITE=1 is set in the server's environment. Each tool
wraps one pylamarzocco command, checks the request against the limits the machine reports,
sends it, and reads the setting back.

Deliberately not exposed: back flush, plumb-in, firmware updates and wake-up schedules. They
start something physical or are hard to undo.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from pylamarzocco import LaMarzoccoCloudClient
from pylamarzocco.const import PreExtractionMode, SmartStandByType, SteamTargetLevel
from pylamarzocco.models import PrebrewSettingTimes, SecondsInOut

from .client import LaMarzoccoError, LaMarzoccoService
from .presentation import present

ALLOW_WRITE_ENV = "LAMARZOCCO_MCP_ALLOW_WRITE"

# Seconds to wait before reading a setting back. The cloud needs a moment to reflect a command.
READ_BACK_DELAY = 2.0

WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,  # every setting can be changed back
    idempotent_hint=True,
    open_world_hint=True,
)

NOTE = (
    "La Marzocco's cloud accepted the command. 'after' was read back {delay:g} s later and can "
    "lag behind the machine by a few seconds."
)

Serial = Annotated[
    str | None,
    Field(
        description=(
            "Machine serial number from list_machines. Leave empty to use the configured "
            "machine, or the only machine on the account."
        )
    ),
]


def _widget(dashboard: Any, prefix: str) -> dict[str, Any] | None:
    """The output of the first dashboard widget whose code starts with ``prefix``."""
    widgets = dashboard.get("widgets", []) if isinstance(dashboard, dict) else []
    for widget in widgets:
        output = widget.get("output")
        if str(widget.get("code", "")).startswith(prefix) and isinstance(output, dict):
            return output
    return None


def _check_range(name: str, value: float, low: Any, high: Any) -> None:
    if isinstance(low, int | float) and value < low:
        raise ToolError(f"{name} {value:g} is below this machine's minimum of {low:g}.")
    if isinstance(high, int | float) and value > high:
        raise ToolError(f"{name} {value:g} is above this machine's maximum of {high:g}.")


def register(server: MCPServer[Any], get_service: Callable[[], LaMarzoccoService]) -> None:
    """Add the write tools to ``server``."""

    async def serial_of(serial_number: str | None) -> str:
        try:
            return await get_service().resolve_serial(serial_number)
        except LaMarzoccoError as err:
            raise ToolError(str(err)) from err

    async def read(call: Callable[[LaMarzoccoCloudClient], Awaitable[Any]]) -> Any:
        try:
            return await get_service().fetch(call)
        except LaMarzoccoError as err:
            raise ToolError(str(err)) from err

    async def dashboard(serial: str) -> Any:
        return await read(lambda c: c.get_thing_dashboard(serial))

    async def send(
        serial: str,
        call: Callable[[LaMarzoccoCloudClient], Awaitable[bool]],
        requested: dict[str, Any],
        read_back: Callable[[], Awaitable[Any]],
    ) -> dict[str, Any]:
        try:
            accepted = await get_service().command(call)
        except LaMarzoccoError as err:
            raise ToolError(str(err)) from err
        if not accepted:
            raise ToolError(
                "La Marzocco did not confirm the command. Check the machine's current state "
                "with get_machine_status before retrying."
            )
        await asyncio.sleep(READ_BACK_DELAY)
        return {
            "accepted": True,
            "requested": requested,
            "after": present(await read_back()),
            "note": NOTE.format(delay=READ_BACK_DELAY),
        }

    @server.tool(annotations=WRITE)
    async def set_power(
        on: Annotated[bool, Field(description="true turns the machine on, false to standby.")],
        serial_number: Serial = None,
    ) -> dict[str, Any]:
        """Turn the espresso machine on (brewing mode) or put it in standby.

        Turning it on starts heating the boilers. Only do this when the user asks for it.
        """
        serial = await serial_of(serial_number)

        async def after() -> Any:
            return _widget(await dashboard(serial), "CMMachineStatus")

        return await send(serial, lambda c: c.set_power(serial, on), {"on": on}, after)

    @server.tool(annotations=WRITE)
    async def set_steam(
        on: Annotated[bool, Field(description="true turns the steam boiler on, false off.")],
        serial_number: Serial = None,
    ) -> dict[str, Any]:
        """Turn the steam boiler on or off."""
        serial = await serial_of(serial_number)

        async def after() -> Any:
            return _widget(await dashboard(serial), "CMSteamBoiler")

        return await send(serial, lambda c: c.set_steam(serial, on), {"on": on}, after)

    @server.tool(annotations=WRITE)
    async def set_steam_target_level(
        level: Annotated[
            Literal[1, 2, 3], Field(description="Steam boiler level: 1 (lowest) to 3 (highest).")
        ],
        serial_number: Serial = None,
    ) -> dict[str, Any]:
        """Set the steam boiler level (1-3). For machines with level-based steam, like the
        Linea Micra."""
        serial = await serial_of(serial_number)
        steam = _widget(await dashboard(serial), "CMSteamBoilerLevel")
        if steam is None or steam.get("targetLevelSupported") is False:
            raise ToolError("This machine does not support setting a steam level.")
        target = SteamTargetLevel(f"Level{level}")

        async def after() -> Any:
            return _widget(await dashboard(serial), "CMSteamBoilerLevel")

        return await send(
            serial, lambda c: c.set_steam_target_level(serial, target), {"level": level}, after
        )

    @server.tool(annotations=WRITE)
    async def set_coffee_target_temperature(
        celsius: Annotated[
            float, Field(ge=80, le=100, description="Coffee boiler target in °C, step 0.1.")
        ],
        serial_number: Serial = None,
    ) -> dict[str, Any]:
        """Set the coffee boiler's target temperature in °C."""
        serial = await serial_of(serial_number)
        boiler = _widget(await dashboard(serial), "CMCoffeeBoiler") or {}
        _check_range(
            "Temperature",
            celsius,
            boiler.get("targetTemperatureMin"),
            boiler.get("targetTemperatureMax"),
        )
        celsius = round(celsius, 1)

        async def after() -> Any:
            return _widget(await dashboard(serial), "CMCoffeeBoiler")

        return await send(
            serial,
            lambda c: c.set_coffee_target_temperature(serial, celsius),
            {"celsius": celsius},
            after,
        )

    @server.tool(annotations=WRITE)
    async def set_pre_extraction_mode(
        mode: Annotated[
            Literal["PreBrewing", "PreInfusion", "Disabled"],
            Field(description="Pre-extraction mode. The Linea Micra offers PreBrewing/Disabled."),
        ],
        serial_number: Serial = None,
    ) -> dict[str, Any]:
        """Turn pre-brewing (or pre-infusion, on machines that have it) on or off."""
        serial = await serial_of(serial_number)
        prebrew = _widget(await dashboard(serial), "CMPreBrewing") or {}
        available = prebrew.get("availableModes")
        if isinstance(available, list) and mode not in available:
            raise ToolError(f"This machine supports {', '.join(available)}, not {mode}.")
        target = PreExtractionMode(mode)

        async def after() -> Any:
            return _widget(await dashboard(serial), "CMPreBrewing")

        return await send(
            serial, lambda c: c.change_pre_extraction_mode(serial, target), {"mode": mode}, after
        )

    @server.tool(annotations=WRITE)
    async def set_pre_extraction_times(
        seconds_in: Annotated[
            float, Field(ge=0, le=30, description="Seconds of water in (wetting the puck).")
        ],
        seconds_out: Annotated[float, Field(ge=0, le=30, description="Seconds of pause.")],
        serial_number: Serial = None,
    ) -> dict[str, Any]:
        """Set the pre-brewing times: seconds of water in, then seconds of pause before the
        shot continues."""
        serial = await serial_of(serial_number)
        prebrew = _widget(await dashboard(serial), "CMPreBrewing") or {}
        times = prebrew.get("times") or {}
        entries = times.get(prebrew.get("mode")) or next(iter(times.values()), None) or [{}]
        limits = entries[0] if isinstance(entries, list) and entries else {}
        low, high = limits.get("secondsMin") or {}, limits.get("secondsMax") or {}
        _check_range("seconds_in", seconds_in, low.get("In"), high.get("In"))
        _check_range("seconds_out", seconds_out, low.get("Out"), high.get("Out"))
        setting = PrebrewSettingTimes(
            times=SecondsInOut(seconds_in=seconds_in, seconds_out=seconds_out)
        )

        async def after() -> Any:
            return _widget(await dashboard(serial), "CMPreBrewing")

        return await send(
            serial,
            lambda c: c.change_pre_extraction_times(serial, setting),
            {"seconds_in": round(seconds_in, 1), "seconds_out": round(seconds_out, 1)},
            after,
        )

    @server.tool(annotations=WRITE)
    async def set_smart_standby(
        enabled: Annotated[bool, Field(description="Whether smart standby is on.")],
        minutes: Annotated[
            int, Field(ge=1, le=240, description="Minutes until the machine goes to standby.")
        ],
        after_event: Annotated[
            Literal["LastBrewing", "PowerOn"],
            Field(description="Count the minutes from the last shot or from power-on."),
        ] = "LastBrewing",
        serial_number: Serial = None,
    ) -> dict[str, Any]:
        """Set when the machine goes to standby by itself."""
        serial = await serial_of(serial_number)
        schedule = await read(lambda c: c.get_thing_schedule(serial))
        current = schedule.get("smartStandBy") if isinstance(schedule, dict) else None
        if isinstance(schedule, dict) and schedule.get("smartStandBySupported") is False:
            raise ToolError("This machine does not support smart standby.")
        if isinstance(current, dict):
            _check_range("minutes", minutes, current.get("minutesMin"), current.get("minutesMax"))
        after_type = SmartStandByType(after_event)

        async def read_back() -> Any:
            result = await read(lambda c: c.get_thing_schedule(serial))
            return result.get("smartStandBy") if isinstance(result, dict) else result

        return await send(
            serial,
            lambda c: c.set_smart_standby(serial, enabled, minutes, after_type),
            {"enabled": enabled, "minutes": minutes, "after": after_event},
            read_back,
        )
