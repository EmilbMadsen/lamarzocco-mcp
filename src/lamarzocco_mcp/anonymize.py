"""Remove personal data from La Marzocco API responses before they are committed as fixtures.

Two passes:

1. Collect sensitive values (serial numbers, machine names, emails, tokens, ...) by key.
2. Replace those values everywhere, including inside other strings (URLs, BLE device names such
   as ``MICRA_<serial>``) and dict keys, with stable placeholders like ``SERIAL_1``.

Every value is replaced consistently, so the same serial gets the same placeholder across files
in one run.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# Keys whose values are always secret. They are replaced by a fixed marker, not a placeholder.
SECRET_KEYS = frozenset(
    k.lower()
    for k in (
        "bleAuthToken",
        "accessToken",
        "refreshToken",
        "token",
        "password",
        "secret",
        "privateKey",
        "installationId",
        "Authorization",
    )
)
REDACTED = "**REDACTED**"

# Keys whose values identify the user or machine. Replaced by numbered placeholders.
IDENTIFYING_KEYS: dict[str, str] = {
    "serialnumber": "SERIAL",
    "serial_number": "SERIAL",
    "email": "EMAIL",
    "username": "EMAIL",
    "location": "LOCATION",
    "address": "BT_ADDRESS",
    "macaddress": "MAC_ADDRESS",
    "ssid": "SSID",
    "wifissid": "SSID",
    "wifi_ssid": "SSID",
    "bssid": "SSID",
    "ip": "IP",
    "ipaddress": "IP",
}

# "name" is only personal on a machine/thing object (one that also has a serial number).
_THING_MARKERS = frozenset({"serialnumber", "serial_number"})

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_secrets(data: Any) -> Any:
    """Replace values of secret keys (tokens etc.). Used on raw dumps that stay local."""
    if isinstance(data, dict):
        return {
            k: (REDACTED if str(k).lower() in SECRET_KEYS and v else mask_secrets(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [mask_secrets(v) for v in data]
    return data


@dataclass
class Anonymizer:
    """Collects sensitive values and replaces them with stable placeholders."""

    extra_values: Iterable[str] = ()
    mapping: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value in self.extra_values:
            self._register(value, "REDACTED")

    def _register(self, value: Any, kind: str) -> None:
        if not isinstance(value, str) or not value.strip() or value in self.mapping:
            return
        if value == REDACTED:
            return
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        self.mapping[value] = f"{kind}_{n}"

    def collect(self, data: Any) -> None:
        """First pass: find sensitive values in ``data``."""
        if isinstance(data, dict):
            keys = {str(k).lower() for k in data}
            is_thing = bool(keys & _THING_MARKERS)
            for k, v in data.items():
                key = str(k).lower()
                if key in IDENTIFYING_KEYS:
                    self._register(v, IDENTIFYING_KEYS[key])
                elif key == "name" and is_thing:
                    self._register(v, "MACHINE_NAME")
                self.collect(v)
        elif isinstance(data, list):
            for v in data:
                self.collect(v)
        elif isinstance(data, str):
            for email in EMAIL_RE.findall(data):
                self._register(email, "EMAIL")

    def _replace_in_string(self, text: str) -> str:
        # Longest first, so a serial inside a longer registered value is not replaced early.
        for value in sorted(self.mapping, key=len, reverse=True):
            if value in text:
                text = text.replace(value, self.mapping[value])
        return EMAIL_RE.sub("EMAIL", text)

    def apply(self, data: Any) -> Any:
        """Second pass: return a copy of ``data`` with secrets and identifiers replaced."""
        if isinstance(data, dict):
            out: dict[Any, Any] = {}
            for k, v in data.items():
                new_key = self._replace_in_string(k) if isinstance(k, str) else k
                if str(k).lower() in SECRET_KEYS and v:
                    out[new_key] = REDACTED
                else:
                    out[new_key] = self.apply(v)
            return out
        if isinstance(data, list):
            return [self.apply(v) for v in data]
        if isinstance(data, str):
            return self._replace_in_string(data)
        return data

    def leaks(self, text: str) -> list[str]:
        """Return the placeholders whose original value still appears in ``text``."""
        found = [self.mapping[v] for v in self.mapping if v in text]
        found += [f"email:{m}" for m in EMAIL_RE.findall(text)]
        return found


def anonymize(data: Any, extra_values: Iterable[str] = ()) -> Any:
    """Convenience wrapper for a single document."""
    anonymizer = Anonymizer(extra_values=extra_values)
    anonymizer.collect(data)
    return anonymizer.apply(data)
