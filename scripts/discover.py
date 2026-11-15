"""Phase 0 discovery: record everything pylamarzocco can read from a machine.

Calls every cloud read method and stores the raw JSON responses, then optionally listens on the
cloud WebSocket and the Bluetooth shot counter for a number of minutes. While listening, type a
note and press Enter (e.g. ``scale 28.4s``) to put a timestamped marker in the log, so the
machine's shot times can be compared with a scale timer afterwards.

Raw data goes to ``dumps/<timestamp>/`` (git-ignored). Bluetooth tokens are masked even there.
Run ``scripts/anonymize.py`` before anything from it is committed.

    uv run python scripts/discover.py                     # cloud only
    uv run python scripts/discover.py --minutes 15        # + WebSocket
    uv run python scripts/discover.py --minutes 15 --bluetooth
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum
from http import HTTPMethod
from pathlib import Path
from typing import Any, TextIO

from aiohttp import ClientSession
from pylamarzocco import LaMarzoccoBluetoothClient, LaMarzoccoCloudClient
from pylamarzocco.exceptions import AuthFail, PolicyAcceptanceRequired, RequestNotSuccessful

from lamarzocco_mcp.anonymize import mask_secrets
from lamarzocco_mcp.credentials import (
    CredentialsMissingError,
    load_credentials,
    load_serial_number,
)

DUMPS_DIR = Path(__file__).resolve().parent.parent / "dumps"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def local_timezone_name() -> str:
    """Best-effort IANA timezone name (needed by the coffee trend endpoint)."""
    try:
        target = str(Path("/etc/localtime").resolve())
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


def to_jsonable(obj: Any) -> Any:
    """Convert pylamarzocco models (mashumaro dataclasses) to plain JSON data."""
    if hasattr(obj, "to_dict"):
        return to_jsonable(obj.to_dict())
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, bytes | bytearray):
        return bytes(obj).decode("utf-8", errors="replace")
    return obj


class EventLog:
    """Append-only JSONL log of everything observed while listening."""

    def __init__(self, path: Path) -> None:
        self._file: TextIO = path.open("a", encoding="utf-8")

    def write(self, source: str, kind: str, data: Any = None, quiet: bool = False) -> None:
        entry = {"t": now_iso(), "source": source, "kind": kind, "data": mask_secrets(data)}
        self._file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        self._file.flush()
        if not quiet:
            summary = json.dumps(data, ensure_ascii=False, default=str) if data else ""
            print(f"[{entry['t'][11:23]}] {source:9} {kind:12} {summary[:110]}")

    def close(self) -> None:
        self._file.close()


class RecordingCloudClient(LaMarzoccoCloudClient):
    """Cloud client that keeps a copy of every raw JSON response."""

    recorded: list[dict[str, Any]]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.recorded = []

    async def _rest_api_call(
        self,
        url: str,
        method: HTTPMethod,
        data: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> dict[Any, Any]:
        result = await super()._rest_api_call(url, method, data, timeout)
        self.recorded.append({"t": now_iso(), "method": str(method), "url": url, "raw": result})
        return result


class RawMessageHandler(logging.Handler):
    """Grab raw WebSocket frames and Bluetooth notifications from pylamarzocco's debug logs.

    The library only hands parsed models to callbacks, which can drop unknown fields. The raw
    payloads are what we want to map, so we read them from the log records instead.
    """

    def __init__(self, log: EventLog) -> None:
        super().__init__(level=logging.DEBUG)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.msg == "Received websocket message: %s" and record.args:
                msg = record.args[0] if isinstance(record.args, tuple) else record.args
                payload = getattr(msg, "data", msg)
                self._log.write("websocket", "raw", self._decode(payload), quiet=True)
            elif record.msg == "Shot counter received data: %s" and record.args:
                payload = record.args[0] if isinstance(record.args, tuple) else record.args
                self._log.write("bluetooth", "raw", self._decode(payload), quiet=True)
        except Exception:  # never let logging break the run
            pass

    @staticmethod
    def _decode(payload: Any) -> Any:
        if isinstance(payload, bytes | bytearray):
            payload = bytes(payload).strip(b"\x00").decode("utf-8", errors="replace")
        if isinstance(payload, str):
            # STOMP frame: headers, blank line, JSON body, NUL terminator
            body = payload.split("\n\n", 1)[-1].rstrip("\x00")
            try:
                return json.loads(body)
            except ValueError:
                return payload
        return str(payload)


async def call_all_cloud_reads(
    client: RecordingCloudClient, serial: str, days: int, tz: str
) -> dict[str, Any]:
    """Call every read method. Failures are recorded, not fatal."""
    calls: dict[str, Callable[[], Awaitable[Any]]] = {
        "list_things": client.list_things,
        "get_thing_dashboard": lambda: client.get_thing_dashboard(serial),
        "get_thing_settings": lambda: client.get_thing_settings(serial),
        "get_thing_statistics": lambda: client.get_thing_statistics(serial),
        "get_thing_firmware": lambda: client.get_thing_firmware(serial),
        "get_thing_schedule": lambda: client.get_thing_schedule(serial),
        "get_thing_coffee_and_flush_counter": lambda: client.get_thing_coffee_and_flush_counter(
            serial
        ),
        "get_thing_last_coffee": lambda: client.get_thing_last_coffee(serial, days=days),
        "get_thing_coffee_and_flush_trend": lambda: client.get_thing_coffee_and_flush_trend(
            serial, days=days, timezone=tz
        ),
    }
    results: dict[str, Any] = {}
    for name, call in calls.items():
        before = len(client.recorded)
        try:
            parsed = await call()
            results[name] = {
                "ok": True,
                "parsed": to_jsonable(parsed),
                "raw": [r["raw"] for r in client.recorded[before:]],
            }
            print(f"  ok    {name}")
        except Exception as err:
            results[name] = {
                "ok": False,
                "error": f"{type(err).__name__}: {err}",
                "raw": [r["raw"] for r in client.recorded[before:]],
            }
            print(f"  FAIL  {name}: {type(err).__name__}: {err}")
    return mask_secrets(results)  # type: ignore[no-any-return]


async def listen_websocket(client: LaMarzoccoCloudClient, serial: str, log: EventLog) -> None:
    connects = 0

    def on_connect() -> None:
        nonlocal connects
        connects += 1
        log.write("websocket", "connected", {"count": connects})

    def on_message(config: Any) -> None:
        data = to_jsonable(config)
        widgets = data.get("widgets") if isinstance(data, dict) else None
        codes = [w.get("code") for w in widgets or [] if isinstance(w, dict)]
        log.write("websocket", "parsed", {"widgets": codes}, quiet=False)
        log.write("websocket", "parsed_full", data, quiet=True)

    await client.websocket_connect(
        serial,
        notification_callback=on_message,
        connect_callback=on_connect,
        disconnect_callback=lambda: log.write("websocket", "disconnected"),
    )


async def setup_bluetooth(
    ble_token: str | None, serial: str, log: EventLog
) -> LaMarzoccoBluetoothClient | None:
    if not ble_token:
        log.write("bluetooth", "error", "No bleAuthToken from the cloud for this machine")
        return None

    log.write("bluetooth", "scanning")
    try:
        devices = await LaMarzoccoBluetoothClient.discover_devices()
    except Exception as err:
        log.write("bluetooth", "error", f"Scan failed: {type(err).__name__}: {err}")
        return None
    log.write("bluetooth", "found", [d.name for d in devices])
    if not devices:
        return None

    device = next((d for d in devices if d.name and serial in d.name), devices[0])
    client = LaMarzoccoBluetoothClient(device, ble_token)

    reads: dict[str, Callable[[], Awaitable[Any]]] = {
        "get_machine_capabilities": client.get_machine_capabilities,
        "get_machine_mode": client.get_machine_mode,
        "get_tank_status": client.get_tank_status,
        "get_plumbed_in": client.get_plumbed_in,
        "get_boilers": client.get_boilers,
        "get_smart_standby_settings": client.get_smart_standby_settings,
    }
    for name, call in reads.items():
        try:
            log.write("bluetooth", "read", {name: to_jsonable(await call())})
        except Exception as err:
            log.write("bluetooth", "read_error", {name: f"{type(err).__name__}: {err}"})

    try:
        supported = await client.start_shot_counter(
            callback=lambda u: log.write("bluetooth", "shot_update", to_jsonable(u)),
            connection_callback=lambda c: log.write("bluetooth", "connection", {"up": c}),
            telemetry_callback=lambda t: log.write(
                "bluetooth", "telemetry", to_jsonable(t), quiet=True
            ),
        )
    except Exception as err:
        log.write("bluetooth", "error", f"Shot counter: {type(err).__name__}: {err}")
        supported = False
    log.write("bluetooth", "shot_counter_supported", {"supported": supported})
    return client


def start_note_reader(loop: asyncio.AbstractEventLoop, log: EventLog) -> None:
    """Read notes from stdin on a daemon thread, so it never blocks shutdown."""

    def reader() -> None:
        for line in sys.stdin:
            note = line.strip()
            if note:
                loop.call_soon_threadsafe(log.write, "note", "note", note)

    threading.Thread(target=reader, daemon=True).start()


async def run(args: argparse.Namespace) -> int:
    try:
        creds = load_credentials()
        serial = load_serial_number()
    except CredentialsMissingError as err:
        print(err, file=sys.stderr)
        return 1

    out_dir = DUMPS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    tz = args.timezone or local_timezone_name()
    meta = {
        "started": now_iso(),
        "minutes": args.minutes,
        "websocket": args.minutes > 0 and not args.no_websocket,
        "bluetooth": args.minutes > 0 and args.bluetooth,
        "days": args.days,
        "timezone": tz,
        "python": sys.version.split()[0],
    }

    async with ClientSession() as session:
        client = RecordingCloudClient(
            username=creds.username,
            password=creds.password,
            installation_key=creds.installation_key,
            client=session,
        )

        print("Cloud read methods:")
        try:
            cloud = await call_all_cloud_reads(client, serial, args.days, tz)
        except (AuthFail, PolicyAcceptanceRequired, RequestNotSuccessful) as err:
            print(f"Could not talk to La Marzocco: {err}", file=sys.stderr)
            return 1
        (out_dir / "cloud_before.json").write_text(
            json.dumps(cloud, indent=2, ensure_ascii=False, default=str)
        )

        if args.minutes > 0:
            thing = next((t for t in await client.list_things() if t.serial_number == serial), None)
            ble_token = thing.ble_auth_token if thing else None
            meta["shot_counter_supported_by_cloud"] = (
                thing.shot_counter_supported if thing else None
            )

            log = EventLog(out_dir / "events.jsonl")
            handler = RawMessageHandler(log)
            for name in ("pylamarzocco.clients._cloud", "pylamarzocco.clients._bluetooth"):
                lib_logger = logging.getLogger(name)
                lib_logger.setLevel(logging.DEBUG)
                lib_logger.addHandler(handler)
                lib_logger.propagate = False

            tasks: list[asyncio.Task[Any]] = []
            ble_client: LaMarzoccoBluetoothClient | None = None
            if not args.no_websocket:
                tasks.append(asyncio.create_task(listen_websocket(client, serial, log)))
            if args.bluetooth:
                ble_client = await setup_bluetooth(ble_token, serial, log)

            start_note_reader(asyncio.get_running_loop(), log)
            print(
                f"\nListening for {args.minutes} min. Pull some shots. "
                "Type a note + Enter to mark it (e.g. 'scale 28.4s'). Ctrl-C stops early.\n"
            )
            started = time.monotonic()
            try:
                await asyncio.sleep(args.minutes * 60)
            except asyncio.CancelledError:
                # Ctrl-C: stop listening early but still save and re-read the cloud.
                if (current := asyncio.current_task()) is not None:
                    current.uncancel()
                print("\nStopping early ...")
            finally:
                meta["listened_seconds"] = round(time.monotonic() - started)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if ble_client is not None:
                    await ble_client.disconnect()
                log.close()

            print("\nCloud read methods after listening:")
            cloud_after = await call_all_cloud_reads(client, serial, args.days, tz)
            (out_dir / "cloud_after.json").write_text(
                json.dumps(cloud_after, indent=2, ensure_ascii=False, default=str)
            )

    meta["finished"] = now_iso()
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"\nRaw data saved in {out_dir.relative_to(DUMPS_DIR.parent)}/ (not in git).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--minutes", type=float, default=0, help="listen time; 0 = cloud reads only"
    )
    parser.add_argument("--no-websocket", action="store_true", help="skip the WebSocket")
    parser.add_argument("--bluetooth", action="store_true", help="also try Bluetooth")
    parser.add_argument("--days", type=int, default=7, help="days of history to request")
    parser.add_argument("--timezone", help="IANA timezone (default: system timezone)")
    try:
        return asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
