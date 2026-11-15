"""Shape raw API responses before they reach the model.

Everything a tool returns lands in the model's context and the conversation transcript, so:

- Secrets and personal data the model does not need are removed (Bluetooth token, wifi name).
- Image and tutorial URLs are dropped; they are noise for a model and repeat on every response.
- Epoch-millisecond timestamps become ISO 8601 strings in local time, because models are
  unreliable at converting epoch values themselves.

Nothing else is changed: field names and values stay as La Marzocco sends them.
"""

from __future__ import annotations

import re
from datetime import datetime, tzinfo
from typing import Any

REDACTED = "[redacted by lamarzocco-mcp]"

# Secret, or personal and not needed to answer questions about coffee.
PRIVATE_KEYS = frozenset({"bleAuthToken", "wifiSsid"})

_NOISE_KEY = re.compile(r"^imageUrl|tutorialUrl$", re.IGNORECASE)
_TIME_KEY = re.compile(r"(time|date|timestamp)$", re.IGNORECASE)

# Epoch milliseconds between 2001 and 2286; keeps durations and counters untouched.
_MIN_EPOCH_MS = 1_000_000_000_000
_MAX_EPOCH_MS = 9_999_999_999_999


def _to_iso(epoch_ms: int, tz: tzinfo | None) -> str:
    moment = datetime.fromtimestamp(epoch_ms / 1000).astimezone(tz)
    return moment.isoformat(timespec="seconds")


def present(data: Any, tz: tzinfo | None = None) -> Any:
    """Return a copy of ``data`` ready to hand to the model. ``tz`` defaults to local time."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if _NOISE_KEY.search(key):
                continue
            if key in PRIVATE_KEYS:
                out[key] = REDACTED if value else value
            elif (
                _TIME_KEY.search(key)
                and isinstance(value, int)
                and not isinstance(value, bool)
                and _MIN_EPOCH_MS <= value <= _MAX_EPOCH_MS
            ):
                out[key] = _to_iso(value, tz)
            else:
                out[key] = present(value, tz)
        return out
    if isinstance(data, list):
        return [present(item, tz) for item in data]
    return data
