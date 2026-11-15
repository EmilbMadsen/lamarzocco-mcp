"""The console script and where the serial number comes from. No keyring or network needed."""

from __future__ import annotations

from pathlib import Path

import keyring
import pytest

from lamarzocco_mcp import __version__, credentials
from lamarzocco_mcp import server as srv


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        srv.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_setup_delete_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def fake_setup(delete: bool = False) -> int:
        calls.append(delete)
        return 0

    monkeypatch.setattr(srv, "run_setup", fake_setup)
    with pytest.raises(SystemExit) as exc:
        srv.main(["setup", "--delete"])
    assert exc.value.code == 0
    assert calls == [True]


def test_no_arguments_runs_the_stdio_server(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(srv.server, "run", lambda transport: ran.append(transport))
    srv.main([])
    assert ran == ["stdio"]


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    store: dict[str, str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, key: store.get(key))
    monkeypatch.delenv(credentials.SERIAL_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    return store


def test_serial_from_keyring(fake_keyring: dict[str, str]) -> None:
    fake_keyring["serial_number"] = "FROM_KEYRING"
    assert credentials.load_serial_number() == "FROM_KEYRING"


def test_env_overrides_keyring(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_keyring["serial_number"] = "FROM_KEYRING"
    monkeypatch.setenv(credentials.SERIAL_ENV_VAR, "FROM_ENV")
    assert credentials.load_serial_number() == "FROM_ENV"


def test_missing_serial_explains_setup(fake_keyring: dict[str, str]) -> None:
    with pytest.raises(credentials.CredentialsMissingError, match="lamarzocco-mcp setup"):
        credentials.load_serial_number()
