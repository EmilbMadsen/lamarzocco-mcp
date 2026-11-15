import json

from lamarzocco_mcp.anonymize import REDACTED, Anonymizer, anonymize, mask_secrets

THING = {
    "serialNumber": "MR012345",
    "name": "Emils Micra",
    "modelName": "LINEAMICRA",
    "bleAuthToken": "secret-ble-token",
    "imageUrl": "https://example.com/things/MR012345/image.png",
    "widgets": [{"code": "CMMachineStatus", "name": "Machine status"}],
}


def test_secret_keys_are_redacted() -> None:
    out = anonymize(THING)
    assert out["bleAuthToken"] == REDACTED


def test_serial_is_replaced_everywhere_including_urls() -> None:
    out = anonymize(THING)
    assert out["serialNumber"] == "SERIAL_1"
    assert out["imageUrl"] == "https://example.com/things/SERIAL_1/image.png"


def test_machine_name_replaced_but_widget_names_kept() -> None:
    out = anonymize(THING)
    assert out["name"] == "MACHINE_NAME_1"
    assert out["widgets"][0]["name"] == "Machine status"


def test_non_identifying_values_unchanged() -> None:
    out = anonymize(THING)
    assert out["modelName"] == "LINEAMICRA"
    assert out["widgets"][0]["code"] == "CMMachineStatus"


def test_consistent_placeholders_across_documents_and_dict_keys() -> None:
    anonymizer = Anonymizer()
    things = [THING]
    by_url = {"https://api/things/MR012345/dashboard": {"ok": True}}
    events = [{"data": "found MICRA_MR012345"}]
    for doc in (things, by_url, events):
        anonymizer.collect(doc)
    assert anonymizer.apply(by_url) == {"https://api/things/SERIAL_1/dashboard": {"ok": True}}
    assert anonymizer.apply(events) == [{"data": "found MICRA_SERIAL_1"}]


def test_wifi_ssid_from_settings_is_replaced() -> None:
    # Real shape from get_thing_settings on a Linea Micra.
    out = anonymize({"serialNumber": "MR012345", "wifiSsid": "MyHomeNet_2.4", "wifiRssi": -52})
    assert out["wifiSsid"] == "SSID_1"
    assert out["wifiRssi"] == -52


def test_emails_found_anywhere() -> None:
    out = anonymize({"message": "contact someone@example.org please", "username": "a@b.dk"})
    assert "@" not in json.dumps(out)


def test_extra_values() -> None:
    out = anonymize({"note": "pulled by Emil in the kitchen"}, extra_values=["Emil"])
    assert out["note"] == "pulled by REDACTED_1 in the kitchen"


def test_leaks_detects_remaining_values() -> None:
    anonymizer = Anonymizer()
    anonymizer.collect(THING)
    assert anonymizer.leaks(json.dumps(anonymizer.apply(THING))) == []
    assert anonymizer.leaks("MR012345") == ["SERIAL_1"]


def test_mask_secrets_keeps_identifiers() -> None:
    out = mask_secrets({"things": [THING]})
    assert out["things"][0]["bleAuthToken"] == REDACTED
    assert out["things"][0]["serialNumber"] == "MR012345"
