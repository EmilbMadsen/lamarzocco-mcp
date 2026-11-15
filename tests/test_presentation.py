from datetime import UTC

from lamarzocco_mcp.presentation import REDACTED, present


def test_epoch_ms_under_time_keys_becomes_iso() -> None:
    out = present({"time": 1794726152399, "lastCleaningStartTime": 1793376496482}, tz=UTC)
    assert out["time"] == "2026-11-15T07:02:32+00:00"
    assert out["lastCleaningStartTime"].startswith("2026-")


def test_other_numbers_are_untouched() -> None:
    data = {"totalCoffee": 644, "extractionSeconds": 22.136, "time": 5, "count": 1794726152399}
    assert present(data, tz=UTC) == data


def test_booleans_and_nulls_under_time_keys_untouched() -> None:
    data = {"readyStartTime": None, "brewingStartTime": True}
    assert present(data, tz=UTC) == data


def test_private_keys_redacted_only_when_set() -> None:
    out = present({"bleAuthToken": "abc", "wifiSsid": None})
    assert out == {"bleAuthToken": REDACTED, "wifiSsid": None}


def test_noise_urls_dropped_recursively() -> None:
    data = {
        "widgets": [{"code": "X", "tutorialUrl": "https://..."}],
        "imageUrlDetail": "https://...",
    }
    assert present(data) == {"widgets": [{"code": "X"}]}
