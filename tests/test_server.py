"""Server tests against anonymized Linea Micra fixtures. No credentials or network needed."""

from __future__ import annotations

import json
import re

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pylamarzocco.exceptions import AuthFail, PolicyAcceptanceRequired, RequestNotSuccessful

from lamarzocco_mcp import server as srv
from lamarzocco_mcp.presentation import REDACTED

from .conftest import SERIAL, Harness

ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

EXPECTED_TOOLS = {
    "list_machines",
    "get_machine_status",
    "get_machine_settings",
    "get_statistics",
    "get_firmware_status",
    "get_schedule",
    "get_coffee_and_flush_counter",
    "get_last_coffees",
    "get_coffee_and_flush_trend",
}


async def test_expected_tools_are_registered_and_read_only() -> None:
    tools = await srv.server.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.annotations is not None and tool.annotations.read_only_hint, tool.name


async def test_pump_time_is_explained_to_the_model() -> None:
    tools = {t.name: t for t in await srv.server.list_tools()}
    assert "pump time" in (tools["get_last_coffees"].description or "")
    assert "pump time" in (srv.server.instructions or "")


async def test_list_machines(harness: Harness) -> None:
    result = await srv.list_machines()
    [machine] = result["machines"]
    assert machine["serialNumber"] == SERIAL
    assert machine["modelName"] == "LINEA MICRA"
    assert machine["bleAuthToken"] == REDACTED
    assert not any(key.startswith("imageUrl") for key in machine)
    assert ISO.match(machine["connectionDate"])


async def test_last_coffees_keep_raw_fields_and_iso_times(harness: Harness) -> None:
    result = await srv.get_last_coffees()
    shots = result["lastCoffees"]
    assert len(shots) == 15
    newest = shots[0]
    assert ISO.match(newest["time"])
    assert newest["extractionSeconds"] == pytest.approx(22.136)
    # Fields pylamarzocco's model drops must survive.
    assert newest["targetTemperature"] == 94
    assert newest["valid"] is True


async def test_last_coffees_limit(harness: Harness) -> None:
    result = await srv.get_last_coffees(limit=3)
    assert len(result["lastCoffees"]) == 3


async def test_machine_status_widgets(harness: Harness) -> None:
    result = await srv.get_machine_status()
    codes = [w["code"] for w in result["widgets"]]
    assert codes[0] == "CMMachineStatus"
    assert result["widgets"][0]["output"]["status"] == "StandBy"
    back_flush = next(w for w in result["widgets"] if w["code"] == "CMBackFlush")
    assert ISO.match(back_flush["output"]["lastCleaningStartTime"])


async def test_settings_hide_wifi_name(harness: Harness) -> None:
    result = await srv.get_machine_settings()
    assert result["wifiSsid"] == REDACTED
    assert result["wifiRssi"] == -52


@pytest.mark.parametrize(
    ("tool", "expected_key"),
    [
        (srv.get_statistics, "selectedWidgets"),
        (srv.get_firmware_status, "status"),
        (srv.get_schedule, "smartStandBy"),
        (srv.get_coffee_and_flush_counter, "totalCoffee"),
        (srv.get_coffee_and_flush_trend, "coffees"),
    ],
)
async def test_other_tools_return_data(harness: Harness, tool: object, expected_key: str) -> None:
    result = await tool()  # type: ignore[operator]
    assert expected_key in result


async def test_trend_passes_days_and_timezone(harness: Harness) -> None:
    await srv.get_coffee_and_flush_trend(days=14)
    assert harness.client is not None
    url = harness.client.urls[-1]
    assert "days=14" in url and "timezone=" in url


async def test_trend_days_are_bounded() -> None:
    with pytest.raises(ToolError):
        await srv.server.call_tool("get_coffee_and_flush_trend", {"days": 90})


async def test_serial_falls_back_to_the_only_machine(harness: Harness) -> None:
    harness.serial = None
    await srv.get_machine_status()
    assert harness.client is not None
    assert harness.client.urls[-1].endswith(f"/things/{SERIAL}/dashboard")


async def test_explicit_serial_wins(harness: Harness) -> None:
    await srv.get_machine_status(serial_number="OTHER")
    assert harness.client is not None
    assert harness.client.urls[-1].endswith("/things/OTHER/dashboard")


async def test_unparseable_response_still_returns_raw(harness: Harness) -> None:
    # A value pylamarzocco's enums do not know yet, e.g. after a firmware update.
    harness.responses["get_thing_last_coffee"]["output"]["lastCoffees"][0]["doseMode"] = "New"
    result = await srv.get_last_coffees(limit=1)
    assert result["lastCoffees"][0]["doseMode"] == "New"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (AuthFail("Invalid username or password"), "setup_credentials.py"),
        (PolicyAcceptanceRequired("policy"), "privacy policy"),
        (RequestNotSuccessful("500"), "API returned an error"),
        (TimeoutError(), "Could not reach"),
    ],
)
async def test_api_errors_become_clear_tool_errors(
    harness: Harness, error: Exception, message: str
) -> None:
    harness.fail_with(error)
    with pytest.raises(ToolError, match=message):
        await srv.get_last_coffees()


async def test_tool_output_is_json_serializable(harness: Harness) -> None:
    for name in EXPECTED_TOOLS:
        result = await srv.server.call_tool(name, {})
        assert not getattr(result, "is_error", False), name
        json.dumps(getattr(result, "structured_content", None))
