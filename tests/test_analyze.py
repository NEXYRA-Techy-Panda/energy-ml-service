"""POST /v1/analyze — deterministic vacant-beyond-grace rule and request validation."""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
V1 = Path(__file__).resolve().parents[1] / "contracts" / "v1"
REFERENCE = json.loads((V1 / "fixtures" / "reference.json").read_text(encoding="utf-8"))
# Evaluation oracle only: used to check results, never sent as an input.
EXPECTED = json.loads((V1 / "fixtures" / "expected.json").read_text(encoding="utf-8"))


def fixture_request() -> dict:
    r = copy.deepcopy(REFERENCE)
    return {
        "contract_version": "1.0.1",
        "dataset_id": "ds-fixture",
        "run_id": r["run"]["run_id"],
        "window": {"start_utc": r["export"]["export_start_utc"], "end_utc": r["export"]["export_end_utc"]},
        "rooms": r["rooms"],
        "devices": r["devices"],
        "policies": r["policies"],
        "room_intervals": r["room_intervals"],
        "device_intervals": r["device_intervals"],
        "options": {"tariff_inr_per_kwh": 10.0},
    }


def minute(i: int) -> str:
    return (datetime(2026, 9, 21, 3, 30, tzinfo=timezone.utc) + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")


def series_request(occupancy: list[float], light_on: list[float], grace: int = 120, standby: float | None = 0.0,
                   occupancy_max: list[int] | None = None) -> dict:
    """Room A + light-a minute series. occupancy = occupied_fraction per minute; light_on = on seconds per minute."""
    n = len(occupancy)
    maxes = occupancy_max or [1 if o > 0 else 0 for o in occupancy]
    device = {"device_id": "light-a", "name": "Room A light", "room_id": "room-a", "device_type": "lighting",
              "always_on": False, "nominal_power_w": 600}
    if standby is not None:
        device["standby_power_w"] = standby
    rooms, devices = [], []
    cumulative = 0.0
    for i in range(n):
        rooms.append({"room_id": "room-a", "interval_start_utc": minute(i), "interval_end_utc": minute(i + 1),
                      "interval_seconds": 60, "occupancy_avg": occupancy[i], "occupancy_max": maxes[i],
                      "occupied_fraction": occupancy[i]})
        on = light_on[i]
        power = 600 * on / 60
        energy = power * 60 / 3_600_000
        cumulative += energy
        vacant_on = on if maxes[i] == 0 else min(on, 60 * (1 - occupancy[i]))
        devices.append({"device_id": "light-a", "room_id": "room-a", "interval_start_utc": minute(i),
                        "interval_end_utc": minute(i + 1), "interval_seconds": 60, "avg_power_w": power,
                        "max_power_w": 600 if on else 0, "energy_kwh": energy, "cumulative_kwh": cumulative,
                        "on_fraction": on / 60, "vacant_on_seconds": vacant_on, "offschedule_on_seconds": 0,
                        "override_seconds": 0, "policy_ref": "pol-light-a:1"})
    return {
        "contract_version": "1.0.1", "dataset_id": "ds-series", "run_id": "run-series",
        "window": {"start_utc": minute(0), "end_utc": minute(n)},
        "rooms": [{"room_id": "room-a", "name": "Room A", "capacity": 4}],
        "devices": [device],
        "policies": [{"policy_id": "pol-light-a", "version": 1, "kind": "lighting_schedule",
                      "rules": {"on_during_hours": True, "vacancy_grace_seconds": grace}}],
        "room_intervals": rooms, "device_intervals": devices,
    }


def post(body) -> tuple[int, dict]:
    res = client.post("/v1/analyze", content=json.dumps(body) if not isinstance(body, (bytes, str)) else body,
                      headers={"Content-Type": "application/json"})
    return res.status_code, res.json()


def ok(body) -> dict:
    status, payload = post(body)
    assert status == 200, payload
    return payload["data"]


def codes(data: dict) -> list[str]:
    return [w["code"] for w in data["warnings"]]


# ---------------------------------------------------------------- findings


def test_reference_fixture_matches_the_oracle_finding():
    status, payload = post(fixture_request())
    assert status == 200
    assert payload["meta"]["request_id"]
    data = payload["data"]
    assert len(data["findings"]) == 1
    f, oracle = data["findings"][0], EXPECTED["findings"][0]
    for key in ("finding_type", "room_id", "device_id", "window_start_utc", "window_end_utc", "method"):
        assert f[key] == oracle[key], key
    assert f["observed"] == oracle["observed"]
    assert f["expected"] == oracle["expected"]
    assert f["avoidable_energy_kwh"] == pytest.approx(oracle["avoidable_energy_kwh"], abs=1e-12)
    assert f["avoidable_cost_inr"] == pytest.approx(0.1, abs=1e-12)
    assert "confidence" not in json.dumps(f) and "probability" not in json.dumps(f)
    assert data["analysis"]["method"] == "rule" and data["analysis"]["model_used"] is False
    assert "ANALYSES_NOT_PERFORMED" in codes(data)


def test_refrigerator_always_on_exception_is_excluded():
    data = ok(fixture_request())
    assert all(f["device_id"] != "fridge-b" for f in data["findings"])
    assert {"device_id": "fridge-b", "reason": "always-on exception: vacant operation is by design"} in data["analysis"]["excluded_devices"]


def test_occupied_room_does_not_trigger():
    data = ok(series_request([1, 1, 1], [60, 60, 60], grace=0))
    assert data["findings"] == []


def test_grace_not_elapsed_does_not_trigger():
    # Vacant from minute 1 (transition observed); grace 120 s ends at minute 3.
    data = ok(series_request([1, 0, 0], [60, 60, 60], grace=120))
    assert data["findings"] == []
    assert "INSUFFICIENT_VACANCY_CONTEXT" not in codes(data)


def test_counts_only_operation_after_grace_expiry():
    data = ok(series_request([1, 0, 0, 0, 0], [60] * 5, grace=120))
    (f,) = data["findings"]
    assert (f["window_start_utc"], f["window_end_utc"]) == (minute(3), minute(5))
    assert f["observed"] == {"value": pytest.approx(0.02), "unit": "kWh"}
    assert f["avoidable_energy_kwh"] == pytest.approx(0.02)


def test_grace_expiring_inside_an_interval_uses_constant_power_only_when_on_throughout():
    data = ok(series_request([1, 0, 0, 0], [60] * 4, grace=90))  # expiry 03:32:30
    (f,) = data["findings"]
    assert f["window_start_utc"] == "2026-09-21T03:32:30Z"
    assert f["avoidable_energy_kwh"] == pytest.approx(600 * (30 + 60) / 3_600_000)
    assert "constant" in f["assumptions"]
    # Partly on in the straddling interval: timing unknown → no claim for it.
    data = ok(series_request([1, 0, 0], [60, 60, 20], grace=90))
    assert data["findings"] == []
    assert "SUB_INTERVAL_TIMING" in codes(data)


def test_insufficient_preceding_context_limits_the_result():
    # Vacant from the first supplied minute: vacancy may have begun earlier.
    data = ok(series_request([0, 0, 0], [60, 60, 60], grace=120))
    (f,) = data["findings"]
    assert f["window_start_utc"] == minute(2)  # counted only after the provable expiry
    assert "INSUFFICIENT_VACANCY_CONTEXT" in codes(data)
    data = ok(series_request([0, 0], [60, 60], grace=300))
    assert data["findings"] == []
    assert "INSUFFICIENT_VACANCY_CONTEXT" in codes(data)


def test_zero_grace_fully_vacant_interval_is_supported_directly():
    data = ok(series_request([0], [60], grace=0))
    assert len(data["findings"]) == 1 and "INSUFFICIENT_VACANCY_CONTEXT" not in codes(data)


def test_mixed_occupancy_is_not_treated_as_fully_vacant():
    data = ok(series_request([1, 0.5, 0.5], [60, 60, 60], grace=0))
    assert data["findings"] == []
    assert codes(data).count("MIXED_OCCUPANCY") == 2


def test_unknown_standby_reports_seconds_without_an_energy_estimate():
    data = ok(series_request([1, 0], [60, 60], grace=0, standby=None))
    (f,) = data["findings"]
    assert f["observed"] == {"value": 60.0, "unit": "s"}
    assert "avoidable_energy_kwh" not in f


def test_manual_override_is_described_not_judged():
    body = series_request([1, 0], [60, 60], grace=0)
    body["device_intervals"][1]["override_seconds"] = 60
    (f,) = ok(body)["findings"]
    assert "manual override for 60 s" in f["assumptions"]


def test_future_policy_is_not_applied_retroactively():
    body = fixture_request()
    body["policies"][1]["effective_from_utc"] = "2026-09-21T03:31:00Z"  # after interval 1 starts
    status, payload = post(body)
    assert status == 400 and payload["error"]["field"] == "device_intervals[0].policy_ref"


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(("mutate", "field"), [
    (lambda b: b["devices"][0].update(room_id="room-x"), "devices[0].room_id"),
    (lambda b: b["device_intervals"][0].update(device_id="dev-x"), "device_intervals[0].device_id"),
    (lambda b: b["device_intervals"][0].update(policy_ref="pol-x:1"), "device_intervals[0].policy_ref"),
    (lambda b: b["device_intervals"][0].update(room_id="room-b"), "device_intervals[0].room_id"),
    (lambda b: b["room_intervals"][0].update(room_id="room-x"), "room_intervals[0].room_id"),
    (lambda b: b["device_intervals"][1].update(energy_kwh=0.02), "device_intervals[1].energy_kwh"),
    (lambda b: b["device_intervals"][1].update(interval_seconds=30), "device_intervals[1].interval_seconds"),
    (lambda b: b["device_intervals"][1].update(interval_start_utc="2026-02-30T03:31:00Z"), "device_intervals[1].interval_start_utc"),
    (lambda b: b["window"].update(end_utc="2026-09-21T03:31:00Z"), "room_intervals[1].interval_start_utc"),
    (lambda b: b["device_intervals"][1].update(max_power_w=100), "device_intervals[1].max_power_w"),
    (lambda b: b["device_intervals"][1].update(on_fraction=1.5), "device_intervals[1].on_fraction"),
    (lambda b: b["policies"][1]["rules"].update(vacancy_grace_seconds=-1), "policies[1]"),
    (lambda b: b["policies"][1].update(applies_to="device:nope"), "policies[1].applies_to"),
    (lambda b: b.pop("window"), "window"),
    (lambda b: b.update(extra=1), "extra"),
])
def test_invalid_requests_are_rejected_with_the_error_envelope(mutate, field):
    body = fixture_request()
    mutate(body)
    status, payload = post(body)
    assert status == 400, payload
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["field"] == field


def test_unsupported_version_and_malformed_json():
    body = fixture_request()
    body["contract_version"] = "1.0.0"
    status, payload = post(body)
    assert (status, payload["error"]["code"]) == (400, "UNSUPPORTED_VERSION")
    status, payload = post("{not json")
    assert (status, payload["error"]["code"]) == (400, "VALIDATION_ERROR")


def test_conflicting_duplicates_rejected_identical_duplicates_deduplicated():
    body = fixture_request()
    body["device_intervals"].append(copy.deepcopy(body["device_intervals"][1]))
    data = ok(body)
    assert data["analysis"]["records"]["duplicates_deduped"] == 1
    assert "DUPLICATES_DEDUPED" in codes(data)
    assert len(data["findings"]) == 1

    body = fixture_request()
    conflicting = copy.deepcopy(body["device_intervals"][1])
    conflicting["vacant_on_seconds"] = 30
    body["device_intervals"].append(conflicting)
    status, payload = post(body)
    assert status == 400 and "Conflicting duplicate" in payload["error"]["message"]


@pytest.mark.parametrize("key", ["device_intervals", "room_intervals"])
def test_oversized_requests_return_413(key):
    body = fixture_request()
    body[key] = [body[key][0]] * 2001
    status, payload = post(body)
    assert status == 413
    assert payload["error"] == {"code": "REQUEST_TOO_LARGE", "field": key,
                                "message": f"{key} has 2001 records; the bound is 2000. Narrow the window and preserve temporal context."}


def test_exactly_2000_records_are_within_bounds():
    body = series_request([1] + [0] * 1999, [60] * 2000, grace=0)
    body["window"]["end_utc"] = minute(2000)
    data = ok(body)
    assert data["analysis"]["records"]["device_intervals"] == 2000
    assert len(data["findings"]) == 1


@pytest.mark.parametrize("path", [
    ("device_intervals", 1, "fault_active"),
    ("room_intervals", 0, "is_fault"),
    ("policies", 1, "rules", "fault_active"),
    ("options", "injected_fault"),
    ("expected_diagnosis",),
])
def test_forbidden_fault_fields_are_rejected_anywhere(path):
    body = fixture_request()
    target = body
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = True
    status, payload = post(body)
    assert status == 400
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["field"].endswith(path[-1])
    assert "forbidden" in payload["error"]["message"]


# ---------------------------------------------------------------- model truthfulness


def test_health_and_model_info_stay_truthful_while_rule_analysis_works():
    assert client.get("/health").json()["data"] == {"status": "ok", "model_available": False}
    info = client.get("/v1/model/info").json()["data"]
    assert info["model_available"] is False and info["model_version"] is None
    assert info["baseline_version"] == "hourly-profile-median-v1"  # statistical baseline, not a trained model
    status, payload = post(fixture_request())
    assert status == 200 and "MODEL_UNAVAILABLE" not in json.dumps(payload)
    assert client.post("/v1/forecast", content=b"{}").json()["error"]["code"] == "VALIDATION_ERROR"  # route exists (P013)
