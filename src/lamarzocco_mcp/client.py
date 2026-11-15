"""Thin async wrapper around pylamarzocco's cloud client.

Tools call pylamarzocco's public methods, but return the raw JSON the API sent rather than the
parsed models: the models drop fields (for example ``targetTemperature`` and ``valid`` on each
shot), and a new enum value from a firmware update would otherwise fail the whole call.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from http import HTTPMethod
from typing import Any

from aiohttp import ClientError, ClientSession
from pylamarzocco import LaMarzoccoCloudClient
from pylamarzocco.exceptions import AuthFail, PolicyAcceptanceRequired, RequestNotSuccessful

from .credentials import CredentialsMissingError, load_credentials, load_serial_number

# Raw responses of the REST calls made in the current task (one tool call = one task).
_captured: ContextVar[list[Any] | None] = ContextVar("_captured", default=None)


class LaMarzoccoError(Exception):
    """An anticipated failure, with a message meant for the user."""


class _ParseError(Exception):
    """The API answered, but pylamarzocco could not parse the response."""


class RawCloudClient(LaMarzoccoCloudClient):
    """Cloud client that keeps the raw JSON of every REST response for the current task."""

    async def _rest_api_call(
        self,
        url: str,
        method: HTTPMethod,
        data: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> dict[Any, Any]:
        result = await self._fetch_json(url, method, data, timeout)
        captured = _captured.get()
        if captured is not None:
            captured.append(result)
        return result

    async def _fetch_json(
        self, url: str, method: HTTPMethod, data: dict[str, Any] | None, timeout: int
    ) -> dict[Any, Any]:
        """The real HTTP call. Overridden in tests."""
        return await super()._rest_api_call(url, method, data, timeout)


ClientFactory = Callable[[ClientSession], RawCloudClient]


def _default_factory(session: ClientSession) -> RawCloudClient:
    creds = load_credentials()
    return RawCloudClient(
        username=creds.username,
        password=creds.password,
        installation_key=creds.installation_key,
        client=session,
    )


class LaMarzoccoService:
    """Owns the HTTP session and the cloud client for the lifetime of the server process."""

    def __init__(
        self,
        client_factory: ClientFactory = _default_factory,
        serial_loader: Callable[[], str] = load_serial_number,
    ) -> None:
        self._client_factory = client_factory
        self._serial_loader = serial_loader
        self._session: ClientSession | None = None
        self._client: RawCloudClient | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> RawCloudClient:
        async with self._lock:
            if self._client is None:
                if self._session is None:
                    self._session = ClientSession()
                # Built lazily, so the server starts (and can list tools) without credentials.
                self._client = self._client_factory(self._session)
            return self._client

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None
        self._client = None

    async def resolve_serial(self, serial_number: str | None) -> str:
        """Use the given serial, else LAMARZOCCO_SERIAL, else the only machine on the account."""
        if serial_number:
            return serial_number
        try:
            return self._serial_loader()
        except CredentialsMissingError:
            pass
        machines = await self.fetch(lambda c: c.list_things())
        serials = [m.get("serialNumber") for m in machines if isinstance(m, dict)]
        if len(serials) == 1 and serials[0]:
            return str(serials[0])
        raise LaMarzoccoError(
            f"{len(serials)} machines on this account and LAMARZOCCO_SERIAL is not set. "
            "Pass serial_number (see list_machines)."
        )

    async def fetch(self, call: Callable[[LaMarzoccoCloudClient], Awaitable[Any]]) -> Any:
        """Run one pylamarzocco read method and return the raw JSON of its last REST response."""
        captured: list[Any] = []
        # If pylamarzocco cannot parse the response (e.g. a new enum value), the raw JSON is
        # still what the API sent, so return it.
        with contextlib.suppress(_ParseError):
            await self._run(call, captured)
        if not captured:
            raise LaMarzoccoError("pylamarzocco made no API call.")
        return captured[-1]

    async def command(self, call: Callable[[LaMarzoccoCloudClient], Awaitable[bool]]) -> bool:
        """Run one pylamarzocco command method and return whether La Marzocco accepted it."""
        try:
            return bool(await self._run(call, []))
        except _ParseError as err:
            raise LaMarzoccoError(
                "La Marzocco answered the command in a format pylamarzocco does not understand. "
                "Check the machine before retrying."
            ) from err

    async def _run(
        self, call: Callable[[LaMarzoccoCloudClient], Awaitable[Any]], captured: list[Any]
    ) -> Any:
        """Call pylamarzocco, capturing raw responses and mapping errors to LaMarzoccoError."""
        token = _captured.set(captured)
        try:
            client = await self._get_client()
            return await call(client)
        except CredentialsMissingError as err:
            raise LaMarzoccoError(str(err)) from err
        except AuthFail as err:
            # Drop the client, so changed credentials are picked up on the next call.
            self._client = None
            raise LaMarzoccoError(
                f"La Marzocco rejected the login ({err}). Run `lamarzocco-mcp setup` again."
            ) from err
        except PolicyAcceptanceRequired as err:
            raise LaMarzoccoError(
                "Accept La Marzocco's latest privacy policy in their app, then try again."
            ) from err
        except RequestNotSuccessful as err:
            raise LaMarzoccoError(f"La Marzocco's API returned an error: {err}") from err
        except (TimeoutError, ClientError) as err:
            raise LaMarzoccoError(
                f"Could not reach La Marzocco's cloud ({type(err).__name__}). Try again later."
            ) from err
        except Exception as err:
            # The API answered, but pylamarzocco failed on the response.
            if captured:
                raise _ParseError() from err
            raise
        finally:
            _captured.reset(token)
