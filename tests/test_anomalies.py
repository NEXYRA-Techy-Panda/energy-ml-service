"""POST /v1/anomalies — excess-consumption deviation detector (P022). SYNTHETIC fixtures only."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.anomalies.synthetic import DEVICES, build_request
from app.main import app

client = TestClient(app)
N = 60  # 60 × 5 min = 5 h per section


def post(body) -> tuple[int, dict]:
    res = client.post("/v1/anomalies", content=body if isinstance(body, (bytes, str)) else json.dumps(body),
                      headers={"Content-Type": "application/json"})
    return res.status_code, res.json()


def ok(body) -> dict:
    status, payload = post(body)
    assert status == 200, payload
    return payload["data"]


def steady(levels: dict[str, float] | None = None, eval_levels: dict[str, float] | None = None, jitter: bool = True):
    base = {"light-a": 72.0, "ws-group": 960.0, "ac-a": 1200.0, "fridge-b": 150.0, **(levels or {})}
    ev = {**base, **(eval_levels or {})}

    def power(section, dev, i):
        level = (base if section == "reference" else ev)[dev]
        return (level * (1 + (0.004 * ((i % 5) - 2) if jitter else 0.0)), 1.0)
    return power


def device(data, dev_id):
    return next(d for d in data["devices"] if d["device_id"] == dev_id)


# ------------------------------------------------------------------ detection behaviour


def test_stable_operation_produces_no_finding_and_reports_what_was_evaluated():
    data = ok(build_request(N, N, steady()))
    assert data["findings"] == []
    assert data["status"] == "evaluated_no_deviation"
    assert data["coverage"]["evaluated"] == 4 * N and data["coverage"]["flagged"] == 0
    assert all(d["status"] == "evaluated_no_deviation" for d in data["devices"])
    assert data["detector"]["model_used"] is False


def test_known_large_increase_is_reported_as_a_deviation_not_a_diagnosis():
    data = ok(build_request(N, N, steady(eval_levels={"light-a": 108.0})))
    assert data["status"] == "findings_detected"
    (f,) = data["findings"]
    assert (f["finding_type"], f["device_id"], f["room_id"], f["intervals"]) == ("excess_consumption_deviation", "light-a", "room-a", N)
    assert f["expected"]["value"] == pytest.approx(72.0, rel=0.01) and f["observed"]["value"] == pytest.approx(108.0, rel=0.01)
    assert f["threshold_w"] == pytest.approx(72.0 + 10.0, rel=0.01)  # floor dominates a tight reference
    assert f["reference_support"] == N and f["method"] == "rule" and f["detector_version"] == "excess-power-mad-v1"
    assert f["deviation"]["watts"] == pytest.approx(36.0, rel=0.02)
    assert "NOT a guaranteed avoidable" in f["energy_note"] and "avoidable_energy_kwh" not in f
    text = json.dumps(f).lower()
    assert "confidence" not in text and "probability" not in text and "does not establish a malfunction" in text
    assert {w["code"] for w in data["warnings"]} >= {"NOT_A_DIAGNOSIS", "DRIFT_NOT_ANALYSED"}


def test_constant_reference_power_uses_the_floor_without_division_by_zero():
    data = ok(build_request(N, N, steady(eval_levels={"light-a": 80.0}, jitter=False)))
    base = device(data, "light-a")["reference"]["baselines_by_interval_seconds"]["300"]
    assert (base["mad_w"], base["robust_sigma_w"], base["threshold_w"]) == (0.0, 0.0, 82.0)
    assert data["findings"] == []  # +8 W is under the 10 W floor
    data = ok(build_request(N, N, steady(eval_levels={"light-a": 90.0}, jitter=False)))
    (f,) = data["findings"]
    assert f["deviation"]["robust_z"] is None and f["deviation"]["ratio"] == pytest.approx(1.25)


def test_normal_on_off_changes_are_not_excess_consumption():
    def power(section, dev, i):
        if dev == "light-a" and section == "evaluation" and i % 2:
            return (0.0, 0.0)  # switched off half the time
        return steady()(section, dev, i)

    data = ok(build_request(N, N, power))
    assert data["findings"] == []
    assert device(data, "light-a")["evaluation"]["excluded"] == {"off": N // 2}


def test_mixed_duty_is_excluded_and_never_divided_by_on_fraction():
    def power(section, dev, i):
        if dev == "light-a" and section == "evaluation" and i < 20:
            return (60.0, 0.5)  # would be 120 W if divided by on_fraction
        return steady()(section, dev, i)

    data = ok(build_request(N, N, power))
    assert data["findings"] == []
    light = device(data, "light-a")
    assert light["evaluation"]["excluded"] == {"mixed_duty": 20} and light["evaluation"]["evaluated"] == N - 20
    assert {"section": "evaluation", "device_id": "light-a", "interval_start_utc": data["exclusions"][0]["interval_start_utc"],
            "reason": "mixed_duty"} in data["exclusions"]


def test_comfort_dependent_ac_is_compared_only_under_comparable_conditions():
    def room(section, room_id, i):
        return ((24.5 if section == "reference" else 29.0), 3.0)

    def power(section, dev, i):
        return (1300.0 if section == "reference" else 1700.0, 1.0) if dev == "ac-a" else steady()(section, dev, i)

    data = ok(build_request(N, N, power, room=room))
    ac = device(data, "ac-a")
    assert all(f["device_id"] != "ac-a" for f in data["findings"])  # a hotter room alone is not an anomaly
    assert ac["status"] == "insufficient_reference" and ac["evaluation"]["insufficient_reference"] == N
    assert "no comparable conditions" in next(iter(ac["evaluation"]["insufficient_reasons"]))

    same_room = lambda s, r, i: (24.5, 3.0)  # noqa: E731
    data = ok(build_request(N, N, power, room=same_room))
    (f,) = [f for f in data["findings"] if f["device_id"] == "ac-a"]
    assert f["expected"]["value"] == pytest.approx(1300.0) and "Comfort-dependent" in f["assumptions"]


def test_comfort_dependent_device_without_room_context_is_unsupported():
    room = lambda s, r, i: None if (s == "evaluation" and r == "room-a") else (25.0, 2.0)  # noqa: E731
    data = ok(build_request(N, N, steady(eval_levels={"ac-a": 3000.0}), room=room))
    ac = device(data, "ac-a")
    assert ac["status"] == "unsupported_context" and ac["evaluation"]["excluded"] == {"no_room_context": N}
    assert all(f["device_id"] != "ac-a" for f in data["findings"])


def test_insufficient_history_is_explicit():
    data = ok(build_request(5, N, steady(eval_levels={"light-a": 200.0})))
    assert data["findings"] == [] and data["status"] == "insufficient_reference"
    assert "5 comparable reference intervals (needs 12)" in device(data, "light-a")["reference"]["baselines_by_interval_seconds"]["300"]["insufficient"]
    data = ok(build_request(20, N, steady()))  # 20 × 5 min = 1.67 h < 2 h span
    assert data["status"] == "insufficient_reference"
    assert "spans 1.67 h" in device(data, "fridge-b")["evaluation"]["insufficient_reasons"].popitem()[0]


def test_reference_outlier_does_not_dominate_the_baseline():
    def power(section, dev, i):
        w, on = steady()(section, dev, i)
        return (w * 10 if (section == "reference" and i in (3, 17)) else w, on)

    data = ok(build_request(N, N, power))
    assert data["findings"] == []
    assert device(data, "ws-group")["reference"]["baselines_by_interval_seconds"]["300"]["median_w"] == pytest.approx(960.0, rel=0.005)


def test_missing_readings_are_not_zero():
    def power(section, dev, i):
        if dev == "light-a" and i % 3 == 0:
            return None  # missing, not 0 W
        return steady()(section, dev, i)

    data = ok(build_request(N, N, power))
    light = device(data, "light-a")
    assert data["findings"] == [] and light["evaluation"]["evaluated"] == N - N // 3
    assert light["reference"]["usable_intervals"] == N - N // 3 and light["evaluation"]["excluded"] == {}
    assert light["reference"]["baselines_by_interval_seconds"]["300"]["median_w"] == pytest.approx(72.0, rel=0.01)


def test_evaluation_observations_cannot_alter_the_reference_baseline():
    a = ok(build_request(N, N, steady()))
    b = ok(build_request(N, N, steady(eval_levels={"light-a": 1e4, "ws-group": 0.5, "fridge-b": 900.0})))
    for dev in ("light-a", "ws-group"):
        assert device(a, dev)["reference"] == device(b, dev)["reference"]


def test_device_groups_are_not_multiplied_by_quantity():
    data = ok(build_request(N, N, steady()))
    assert device(data, "ws-group")["reference"]["baselines_by_interval_seconds"]["300"]["median_w"] == pytest.approx(960.0, rel=0.005)
    devs = copy.deepcopy(DEVICES)
    next(d for d in devs if d["device_id"] == "ws-group")["quantity"] = 1
    other = ok(build_request(N, N, steady(), devices=devs))
    assert device(other, "ws-group")["reference"] == device(data, "ws-group")["reference"]


def test_all_off_evaluation_reports_nothing_evaluated_instead_of_no_findings():
    def power(section, dev, i):
        return steady()(section, dev, i) if section == "reference" else (0.0, 0.0)

    data = ok(build_request(N, N, power))
    assert data["status"] == "no_comparable_observations" and data["coverage"]["evaluated"] == 0
    assert data["coverage"]["excluded"] == {"off": 4 * N}


# ------------------------------------------------------------------ validation


def test_reference_must_end_before_evaluation_starts():
    body = build_request(N, N, steady())
    body["reference"]["window"]["end_utc"] = body["evaluation"]["device_intervals"][5]["interval_end_utc"]
    status, payload = post(body)
    assert status == 400 and payload["error"]["field"] == "reference.window.end_utc"


@pytest.mark.parametrize(("mutate", "field", "status", "code"), [
    (lambda b: b["evaluation"]["device_intervals"][2].update(fault_active=True), "evaluation.device_intervals[2].fault_active", 400, "VALIDATION_ERROR"),
    (lambda b: b["reference"]["device_intervals"][0].update(device_id="dev-x"), "reference.device_intervals[0].device_id", 400, "VALIDATION_ERROR"),
    (lambda b: b["evaluation"]["device_intervals"][0].update(energy_kwh=1.0), "evaluation.device_intervals[0].energy_kwh", 400, "VALIDATION_ERROR"),
    (lambda b: b["evaluation"]["device_intervals"][0].update(interval_start_utc="2026-02-30T00:00:00Z"), "evaluation.device_intervals[0].interval_start_utc", 400, "VALIDATION_ERROR"),
    (lambda b: b.update(detector={"version": "other"}), "detector.version", 400, "VALIDATION_ERROR"),
    (lambda b: b.update(contract_version="1.0.0"), "contract_version", 400, "UNSUPPORTED_VERSION"),
    (lambda b: b["reference"].update(device_intervals=[b["reference"]["device_intervals"][0]] * 2001), "reference.device_intervals", 413, "REQUEST_TOO_LARGE"),
    (lambda b: b["evaluation"].update(room_intervals=[b["evaluation"]["room_intervals"][0]] * 2001), "evaluation.room_intervals", 413, "REQUEST_TOO_LARGE"),
])
def test_invalid_requests_are_rejected(mutate, field, status, code):
    body = build_request(N, N, steady())
    mutate(body)
    got, payload = post(body)
    assert (got, payload["error"]["code"], payload["error"]["field"]) == (status, code, field)


def test_duplicates_identical_do_not_inflate_support_and_conflicting_are_rejected():
    body = build_request(N, N, steady())
    base = ok(body)
    dup = copy.deepcopy(body)
    dup["reference"]["device_intervals"] += copy.deepcopy(dup["reference"]["device_intervals"][:20])
    data = ok(dup)
    assert device(data, "light-a")["reference"] == device(base, "light-a")["reference"]
    assert "DUPLICATES_DEDUPED" in {w["code"] for w in data["warnings"]}
    conflict = copy.deepcopy(body)
    x = copy.deepcopy(conflict["reference"]["device_intervals"][0])
    x["avg_power_w"], x["max_power_w"], x["energy_kwh"] = 70.0, 70.0, 70.0 * 300 / 3_600_000
    conflict["reference"]["device_intervals"].append(x)
    status, payload = post(conflict)
    assert status == 400 and "Conflicting duplicate" in payload["error"]["message"]


def test_non_finite_numbers_are_rejected():
    raw = json.dumps(build_request(N, N, steady())).replace('"avg_temp_c": 25.0', '"avg_temp_c": NaN', 1)
    status, payload = post(raw)
    assert status == 400 and "non-finite" in payload["error"]["message"]
