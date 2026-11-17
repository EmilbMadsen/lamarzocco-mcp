"""Remote mode: credentials from a file, read-only by default, OAuth wiring (mcp-owner-auth)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from mcp_owner_auth import build_app
from mcp_owner_auth.store import AuthStore
from pylamarzocco.util import generate_installation_key
from starlette.testclient import TestClient

from lamarzocco_mcp import credentials
from lamarzocco_mcp import server as srv

PUBLIC = "https://lamarzocco.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
TOTP = pyotp.random_base32()
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def write_credentials(path: Path, **extra: object) -> Path:
    key = generate_installation_key(str(uuid.uuid4()))
    data: dict[str, object] = {
        "username": "me@example.com",
        "password": "pw",
        "installation_key": key.to_dict(),
    }
    data.update(extra)
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path


# -- credentials file -----------------------------------------------------------------------------


def test_credentials_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(credentials.CREDENTIALS_FILE_ENV_VAR, str(write_credentials(tmp_path / "c")))
    monkeypatch.setattr("keyring.get_password", lambda *_: pytest.fail("keyring was used"))
    creds = credentials.load_credentials()
    assert creds.username == "me@example.com"
    assert creds.installation_key.installation_id


def test_serial_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_credentials(tmp_path / "c", serial_number="SERIAL_9")
    monkeypatch.setenv(credentials.CREDENTIALS_FILE_ENV_VAR, str(path))
    monkeypatch.delenv(credentials.SERIAL_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    assert credentials.load_serial_number() == "SERIAL_9"


def test_incomplete_credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "c"
    path.write_text(json.dumps({"username": "me"}))
    monkeypatch.setenv(credentials.CREDENTIALS_FILE_ENV_VAR, str(path))
    with pytest.raises(credentials.CredentialsMissingError, match="installation_key"):
        credentials.load_credentials()


def test_readable_credentials_file_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = write_credentials(tmp_path / "c")
    path.chmod(0o644)
    monkeypatch.setenv(credentials.CREDENTIALS_FILE_ENV_VAR, str(path))
    with caplog.at_level(logging.WARNING):
        credentials.load_credentials()
    assert "chmod 600" in caplog.text and "pw" not in caplog.text


# -- remote server ------------------------------------------------------------------------------


def test_auth_config_is_read_only_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMARZOCCO_MCP_PUBLIC_URL", "https://lm.example")
    monkeypatch.setenv(srv.STATE_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(srv, "ALLOW_WRITE", False)
    config = srv.auth_config()
    assert config.scope == "lamarzocco:read"
    assert config.resource == "https://lm.example/mcp"
    assert "read-only" in config.consent


def test_write_tools_are_refused_remotely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "ALLOW_WRITE", True)
    monkeypatch.delenv(srv.ALLOW_REMOTE_WRITE_ENV, raising=False)
    with pytest.raises(SystemExit) as exit_info:
        srv.main(["serve", "--http"])
    assert exit_info.value.code == 2


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("LAMARZOCCO_MCP_PUBLIC_URL", PUBLIC)
    monkeypatch.setenv(srv.STATE_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(srv, "ALLOW_WRITE", False)
    AuthStore(tmp_path / "auth.db").save_credentials(
        username="owner",
        password="a long enough password",
        totp_secret=TOTP,
        client_id="client",
        client_secret="secret",
    )
    app = build_app(srv.server, srv.auth_config())
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as test_client:
        yield test_client


def test_unauthenticated_mcp_is_401(client: TestClient) -> None:
    assert client.post("/mcp", json={}, headers=MCP_HEADERS).status_code == 401
    metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert metadata["scopes_supported"] == ["lamarzocco:read"]


def test_oauth_flow_lists_read_only_tools(client: TestClient) -> None:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "client",
            "redirect_uri": CALLBACK,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": f"{PUBLIC}/mcp",
        },
    )
    page = client.get(authorize.headers["location"].removeprefix(PUBLIC))
    assert "La Marzocco" in page.text
    form = {
        "request": re.findall(r'name=request value="([^"]+)"', page.text)[0],
        "csrf": re.findall(r'name=csrf value="([^"]+)"', page.text)[0],
    }
    client.post(
        "/login",
        data={
            **form,
            "username": "owner",
            "password": "a long enough password",
            "totp": pyotp.TOTP(TOTP).now(),
        },
    )
    allowed = client.post("/consent", data={**form, "decision": "allow"})
    code = parse_qs(urlsplit(allowed.headers["location"]).query)["code"][0]
    token = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CALLBACK,
            "client_id": "client",
            "client_secret": "secret",
            "code_verifier": verifier,
        },
    ).json()
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token['access_token']}"}
    listed = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers
    )
    tools = listed.json()["result"]["tools"]
    assert {"get_machine_status", "get_last_coffees"} <= {t["name"] for t in tools}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
