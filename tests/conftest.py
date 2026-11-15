"""Fake cloud client that serves the anonymized Linea Micra fixtures. No network, no keyring."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import AsyncIterator, Callable
from http import HTTPMethod
from pathlib import Path
from typing import Any

import pytest
from aiohttp import ClientSession
from pylamarzocco.util import generate_installation_key

from lamarzocco_mcp import server as server_module
from lamarzocco_mcp.client import LaMarzoccoService, RawCloudClient
from lamarzocco_mcp.credentials import CredentialsMissingError

FIXTURES = Path(__file__).parent / "fixtures" / "linea_micra"
SERIAL = "SERIAL_1"

# URL path (after /api/customer-app) -> fixture key in cloud_before.json
ROUTES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/things$"), "list_things"),
    (re.compile(r"/things/[^/]+/dashboard$"), "get_thing_dashboard"),
    (re.compile(r"/things/[^/]+/settings$"), "get_thing_settings"),
    (re.compile(r"/things/[^/]+/stats$"), "get_thing_statistics"),
    (re.compile(r"/things/[^/]+/update-fw$"), "get_thing_firmware"),
    (re.compile(r"/things/[^/]+/scheduling$"), "get_thing_schedule"),
    (re.compile(r"/stats/COFFEE_AND_FLUSH_COUNTER/1"), "get_thing_coffee_and_flush_counter"),
    (re.compile(r"/stats/LAST_COFFEE/1"), "get_thing_last_coffee"),
    (re.compile(r"/stats/COFFEE_AND_FLUSH_TREND/1"), "get_thing_coffee_and_flush_trend"),
]


def load_fixture_responses() -> dict[str, Any]:
    data = json.loads((FIXTURES / "cloud_before.json").read_text())
    return {name: entry["raw"][-1] for name, entry in data.items()}


class FakeCloudClient(RawCloudClient):
    """Answers REST calls from fixtures. ``error`` makes every call raise instead."""

    def __init__(self, session: ClientSession, responses: dict[str, Any]) -> None:
        super().__init__(
            username="test@example.com",
            password="not-a-password",
            installation_key=generate_installation_key("test-installation"),
            client=session,
        )
        self.responses = responses
        self.urls: list[str] = []
        self.error: Exception | None = None

    async def _fetch_json(
        self, url: str, method: HTTPMethod, data: dict[str, Any] | None, timeout: int
    ) -> Any:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        path = url.split("?", 1)[0]
        for pattern, name in ROUTES:
            if pattern.search(path):
                return copy.deepcopy(self.responses[name])
        raise AssertionError(f"No fixture for {url}")


class Harness:
    def __init__(self) -> None:
        self.responses = load_fixture_responses()
        self.client: FakeCloudClient | None = None
        self.serial: str | None = SERIAL

    def factory(self, session: ClientSession) -> FakeCloudClient:
        self.client = FakeCloudClient(session, self.responses)
        return self.client

    def serial_loader(self) -> str:
        if self.serial is None:
            raise CredentialsMissingError("not set")
        return self.serial

    def fail_with(self, error: Exception) -> None:
        """Make the next calls raise ``error``."""
        original: Callable[[ClientSession], FakeCloudClient] = self.factory

        def failing(session: ClientSession) -> FakeCloudClient:
            client = original(session)
            client.error = error
            return client

        self.factory = failing  # type: ignore[method-assign]


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    h = Harness()
    service = LaMarzoccoService(
        client_factory=lambda session: h.factory(session),
        serial_loader=lambda: h.serial_loader(),
    )
    monkeypatch.setattr(server_module, "service", service)
    yield h
    await service.close()
