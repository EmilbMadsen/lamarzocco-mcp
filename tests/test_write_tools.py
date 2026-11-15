"""Write tools: only behind the flag, validated against the machine's limits, read back after."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from lamarzocco_mcp import server as srv
from lamarzocco_mcp import write_tools

from .conftest import Harness

WRITE_TOOLS = {
    "set_power",
    "set_steam",
    "set_steam_target_level",
    "set_coffee_target_temperature",
    "set_pre_extraction_mode",
    "set_pre_extraction_times",
    "set_smart_standby",
}


@pytest.fixture
def write_server(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> MCPServer[Any]:
    monkeypatch.setattr(write_tools, "READ_BACK_DELAY", 0)
    server: MCPServer[Any] = MCPServer(name="test")
    assert harness.service is not None
    service = harness.service
    write_tools.register(server, lambda: service)
    return server


async def call(server: MCPServer[Any], name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await server.call_tool(name, args)
    content = getattr(result, "structured_content", None)
    assert isinstance(content, dict)
    return content


def commands(harness: Harness) -> list[tuple[str, dict[str, Any] | None]]:
    assert harness.client is not None
    return harness.client.commands


async def test_default_server_has_no_write_tools() -> None:
    assert not srv.ALLOW_WRITE
    names = {t.name for t in await srv.server.list_tools()}
    assert not names & WRITE_TOOLS
    assert "read-only" in (srv.server.instructions or "")


async def test_register_adds_exactly_the_seven_tools(write_server: MCPServer[Any]) -> None:
    tools = await write_server.list_tools()
    assert {t.name for t in tools} == WRITE_TOOLS
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False, tool.name


async def test_set_power_on(harness: Harness, write_server: MCPServer[Any]) -> None:
    result = await call(write_server, "set_power", {"on": True})
    assert commands(harness) == [("CoffeeMachineChangeMode", {"mode": "BrewingMode"})]
    assert result["accepted"] is True
    assert result["after"]["status"] == "StandBy"  # fixture state, read back after the command


async def test_set_power_off(harness: Harness, write_server: MCPServer[Any]) -> None:
    await call(write_server, "set_power", {"on": False})
    assert commands(harness) == [("CoffeeMachineChangeMode", {"mode": "StandBy"})]


async def test_set_steam(harness: Harness, write_server: MCPServer[Any]) -> None:
    result = await call(write_server, "set_steam", {"on": False})
    assert commands(harness) == [
        ("CoffeeMachineSettingSteamBoilerEnabled", {"boilerIndex": 1, "enabled": False})
    ]
    assert result["after"]["targetLevel"] == "Level2"


async def test_set_steam_target_level(harness: Harness, write_server: MCPServer[Any]) -> None:
    await call(write_server, "set_steam_target_level", {"level": 3})
    assert commands(harness) == [
        ("CoffeeMachineSettingSteamBoilerTargetLevel", {"boilerIndex": 1, "targetLevel": "Level3"})
    ]


async def test_steam_level_out_of_range_is_rejected(write_server: MCPServer[Any]) -> None:
    with pytest.raises(ToolError):
        await write_server.call_tool("set_steam_target_level", {"level": 4})


async def test_set_coffee_temperature(harness: Harness, write_server: MCPServer[Any]) -> None:
    result = await call(write_server, "set_coffee_target_temperature", {"celsius": 93.5})
    assert commands(harness) == [
        (
            "CoffeeMachineSettingCoffeeBoilerTargetTemperature",
            {"boilerIndex": 1, "targetTemperature": 93.5},
        )
    ]
    assert result["requested"] == {"celsius": 93.5}


async def test_coffee_temperature_checked_against_machine_limits(
    harness: Harness, write_server: MCPServer[Any]
) -> None:
    widgets = harness.responses["get_thing_dashboard"]["widgets"]
    boiler = next(w for w in widgets if w["code"] == "CMCoffeeBoiler")
    boiler["output"]["targetTemperatureMax"] = 96
    with pytest.raises(ToolError, match="maximum of 96"):
        await write_server.call_tool("set_coffee_target_temperature", {"celsius": 98})
    assert commands(harness) == []


async def test_coffee_temperature_hard_bounds(write_server: MCPServer[Any]) -> None:
    with pytest.raises(ToolError):
        await write_server.call_tool("set_coffee_target_temperature", {"celsius": 120})


async def test_pre_extraction_mode(harness: Harness, write_server: MCPServer[Any]) -> None:
    await call(write_server, "set_pre_extraction_mode", {"mode": "PreBrewing"})
    assert commands(harness) == [("CoffeeMachinePreBrewingChangeMode", {"mode": "PreBrewing"})]


async def test_unsupported_pre_extraction_mode_is_rejected(
    harness: Harness, write_server: MCPServer[Any]
) -> None:
    # The Micra offers PreBrewing and Disabled, not PreInfusion.
    with pytest.raises(ToolError, match="PreBrewing, Disabled"):
        await write_server.call_tool("set_pre_extraction_mode", {"mode": "PreInfusion"})
    assert commands(harness) == []


async def test_pre_extraction_times(harness: Harness, write_server: MCPServer[Any]) -> None:
    await call(write_server, "set_pre_extraction_times", {"seconds_in": 2.5, "seconds_out": 6})
    assert commands(harness) == [
        (
            "CoffeeMachinePreBrewingSettingTimes",
            {"times": {"In": 2.5, "Out": 6.0}, "groupIndex": 1, "doseIndex": "ByGroup"},
        )
    ]


async def test_pre_extraction_times_checked_against_machine_limits(
    harness: Harness, write_server: MCPServer[Any]
) -> None:
    with pytest.raises(ToolError, match="maximum of 9"):
        await write_server.call_tool(
            "set_pre_extraction_times", {"seconds_in": 2, "seconds_out": 9.5}
        )
    assert commands(harness) == []


async def test_smart_standby(harness: Harness, write_server: MCPServer[Any]) -> None:
    result = await call(write_server, "set_smart_standby", {"enabled": True, "minutes": 45})
    assert commands(harness) == [
        (
            "CoffeeMachineSettingSmartStandBy",
            {"enabled": True, "minutes": 45, "after": "LastBrewing"},
        )
    ]
    assert result["after"]["minutesMax"] == 240


async def test_smart_standby_bounds(write_server: MCPServer[Any]) -> None:
    with pytest.raises(ToolError):
        await write_server.call_tool("set_smart_standby", {"enabled": True, "minutes": 500})


async def test_api_error_on_command_is_a_clear_tool_error(
    harness: Harness, write_server: MCPServer[Any]
) -> None:
    from pylamarzocco.exceptions import RequestNotSuccessful

    harness.fail_with(RequestNotSuccessful("boom"))
    with pytest.raises(ToolError, match="API returned an error"):
        await write_server.call_tool("set_steam", {"on": True})
