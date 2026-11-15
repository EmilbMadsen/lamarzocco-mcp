# Capabilities by model

What each La Marzocco machine returns from pylamarzocco's cloud client. lamarzocco-mcp wraps these
methods 1:1 as MCP tools. WebSocket and Bluetooth are out of scope.

Filled in from `scripts/discover.py` runs. To add your model, see [CONTRIBUTING](../CONTRIBUTING.md)
(coming soon): run discovery, anonymize the dump with `scripts/anonymize.py`, and add a column and
a section below.

Legend: ✅ works · ⚠️ partial / caveat · ❌ not available · ❔ not tested yet

## Summary

| Data | pylamarzocco method | Linea Micra |
|---|---|---|
| Machine list (model, name, serial) | `list_things` | ✅ |
| Status: on/standby, boilers, pre-brew, back flush | `get_thing_dashboard` | ✅ |
| Settings: firmware, wifi, plumb-in, auto-update | `get_thing_settings` | ✅ |
| Statistics widgets | `get_thing_statistics` | ✅ (LAST_COFFEE + counter) |
| Firmware update status | `get_thing_firmware` | ✅ |
| Smart standby / wake-up schedule | `get_thing_schedule` | ✅ |
| Total coffees / flushes | `get_thing_coffee_and_flush_counter` | ✅ |
| Latest 15 shots (time, extraction seconds, dose) | `get_thing_last_coffee` | ⚠️ `days` is ignored |
| Coffees and flushes per day | `get_thing_coffee_and_flush_trend` | ⚠️ times out at `days=90` |

## Last coffees

`get_thing_last_coffee(serial, days=N)` returns individual shots, newest first.
**It always returns the latest 15 shots; the `days` parameter is ignored.** Tested with `days` = 1,
7, 14, 30, 60, 90, 180, 365 and 1000: every call returned the same 15 shots, while the trend
endpoint counted 50 coffees in the last 30 days. Raw entry:

```json
{
  "time": 1794726152399,
  "extractionSeconds": 22.136,
  "doseMode": "Continuous",
  "doseIndex": "Continuous",
  "doseValue": null,
  "doseValueNumerator": null,
  "targetTemperature": 94,
  "valid": true,
  "invalidReason": null
}
```

- `time` is epoch milliseconds (UTC), recorded at the end of the shot.
- `extractionSeconds` is **pump time**, not the time a scale timer shows. Confirmed on the Micra.
- pylamarzocco's `LastCoffee` model drops `targetTemperature`, `valid`, `invalidReason` and
  `doseValue`; only `time`, `extraction_seconds`, `dose_mode`, `dose_index` and
  `dose_value_numerator` survive parsing.

## Open questions (phase 0)

- [x] **Which fields does `get_thing_statistics()` return for the Micra?** Two selected widgets:
      `LAST_COFFEE` (the shot list above) and `COFFEE_AND_FLUSH_COUNTER` (`totalCoffee`,
      `totalFlush`). `COFFEE_AND_FLUSH_TREND` is available via its own call. No averages.
- [x] **Is `extractionSeconds` pump time?** Yes.
- [x] **How many shots does `get_thing_last_coffee` return?** The latest 15, whatever `days` is.
- WebSocket stability and the Bluetooth shot counter: out of scope.

## Linea Micra

- Firmware: machine v1.17, gateway v7.5.3 (ESP32)
- Tested: 2026-11-15, pylamarzocco 2.5.6
- Fixtures: [`tests/fixtures/linea_micra/`](../tests/fixtures/linea_micra/)

- **Dashboard widgets:** `CMMachineStatus`, `CMCoffeeBoiler`, `CMSteamBoilerLevel`,
  `CMPreBrewing`, `CMBackFlush`. In standby, `CMMachineStatus.lastCoffee` and `lastFlush` are
  `null`, so the dashboard is not a reliable source for the last shot; use `get_thing_last_coffee`.
- **Coffee boiler:** target temperature 80–100 °C, step 0.1.
- **Steam boiler:** level-based (`targetLevel`, e.g. `Level2`), not a temperature. The response
  does not list the allowed levels.
- **Pre-brewing:** modes `PreBrewing` / `Disabled`, with `In` and `Out` seconds (1–9 s, step 0.1).
- **Back flush:** `lastCleaningStartTime` (epoch ms) and status.
- **Settings:** firmware versions, `wifiSsid` and `wifiRssi` (personal: anonymized in fixtures),
  plumb-in supported, auto-update.
- **Schedule:** smart standby (minutes after last brew), smart wake-up/sleep schedules, early start.
  Weekly and auto on/off are not supported on the Micra.
- **Trend:** one bucket per local day (needs an IANA timezone), separate counts for coffees and
  flushes. Worked with `days=30`; `days=90` hit pylamarzocco's 10 s timeout.
