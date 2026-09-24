"""POST /v1/drift — gradual upward power-trend detector (P024). SYNTHETIC development cases only
(held-out diagnostic seeds live in scripts/evaluate_drift_detector.py)."""

import copy
import json
import random

import pytest
from fastapi.testclient import TestClient

from app.anomalies.synthetic import DEVICES
from app.drift.synthetic import HOURS, build_drift_request, default_room, scenario_power
from app.main import app

client = TestClient(app)


def post(body):
    res = client.post("/v1/drift", content=body if isinstance(body, (bytes, str)) else json.dumps(body),
                      headers={"Content-Type": "application/json"})
    return res.status_code, res.json()


def ok(body) -> dict:
    status, payload = post(body)
    assert status == 200, payload
    return payload["data"]


def case(scenarios: dict | None = None, ref_days=14, eval_days=28, seed=3, **kw) -> dict:
    return build_drift_request(ref_days, eval_days, scenario_power(scenarios or {}, eval_days, random.Random(seed)), **kw)


def dev(data, device_id):
    return next(d for d in data["devices"] if d["device_id"] == device_id)


# ------------------------------------------------------------------ classification


def test_stable_series_is_evaluated_without_a_trend():
    data = ok(case())
    assert data["status"] == "evaluated_no_gradual_trend" and data["findings"] == []
    assert data["coverage"]["evaluated"] == 4
    assert {d["classification"] for d in data["devices"]} == {"stable"}
    assert data["detector"]["model_used"] is False


def test_gradual_material_increase_is_a_sustained_trend_finding():
    data = ok(case({"light-a": {"kind": "gradual", "total": 0.25}}))
    assert data["status"] == "findings_detected"
    (f,) = data["findings"]
    assert f["title"] == "Sustained upward power trend under matched observed conditions"
    assert f["device_id"] == "light-a" and f["room_id"] == "room-a" and f["reference_level_w"] == pytest.approx(72.0, rel=0.02)
    assert f["trend"]["relative_change_over_period"] == pytest.approx(0.25, abs=0.04)
    assert f["trend"]["watts_per_day"] == pytest.approx(72 * 0.25 / 27, rel=0.2)
    assert f["support"]["evaluation_days"] == 28 and f["support"]["reference_days"] == 14
    assert f["method"] == "rule" and f["detector_version"] == "gradual-power-trend-v1"
    text = json.dumps(f).lower()
    for banned in ("confidence", "probability", "p-value", "significan"):
        assert banned not in text
    keys = set(f) | set(f["trend"])
    assert not keys & {"avoidable_energy_kwh", "avoidable_cost_inr", "annual_savings", "roi", "savings"}
    assert "does not establish reduced efficiency" in text and "no avoidable-energy, savings or roi estimate" in text


def test_small_increase_below_practical_threshold_is_not_a_finding():
    data = ok(case({"light-a": {"kind": "small", "total": 0.04}}))
    assert data["findings"] == [] and dev(data, "light-a")["classification"] == "stable"


def test_single_isolated_spike_is_not_a_trend():
    data = ok(case({"fridge-b": {"kind": "spike", "day": 20, "factor": 1.9}}))
    fridge = dev(data, "fridge-b")
    assert data["findings"] == [] and fridge["classification"] == "stable"
    assert fridge["spike_days"] == ["2026-02-08"]


def test_abrupt_step_is_reported_as_a_level_change_not_gradual_drift():
    data = ok(case({"ac-a": {"kind": "step", "day": 14, "size": 0.3}}))
    assert data["findings"] == []
    (change,) = data["other_changes"]
    assert (change["device_id"], change["classification"]) == ("ac-a", "abrupt_level_change")
    assert change["metrics"]["best_step"]["at_local_date"] == "2026-02-02"


def test_elevated_level_from_the_start_is_an_offset_not_a_trend():
    data = ok(case({"light-a": {"kind": "offset", "size": 0.25}}))
    assert data["findings"] == [] and dev(data, "light-a")["classification"] == "level_offset_without_trend"


def test_missing_days_and_irregular_observations_are_not_bridged():
    gen = scenario_power({"light-a": {"kind": "gradual", "total": 0.3}}, 28, random.Random(4))
    rng = random.Random(9)
    dropped = {d for d in range(28) if d % 3 == 1}  # a third of days missing

    def power(section, device, day, hour):
        if section == "evaluation" and day in dropped:
            return None
        return None if rng.random() < 0.2 else gen(section, device, day, hour)  # irregular hours

    data = ok(build_drift_request(14, 28, power))
    light = dev(data, "light-a")
    assert light["support"]["evaluation_days"] <= 28 - len(dropped) and light["classification"] == "sustained_upward_trend"
    days = [d["local_date"] for d in data["findings"][0]["evidence"]["daily"]]
    assert len(days) == light["support"]["evaluation_days"]  # only observed days, nothing interpolated

    sparse = {d for d in range(28) if d % 5}  # keep 1 day in 5 → coverage < 50 %
    data = ok(build_drift_request(14, 28, lambda s, d, day, h: None if (s == "evaluation" and day in sparse) else gen(s, d, day, h)))
    assert dev(data, "light-a")["status"] == "insufficient_history" and "coverage" in dev(data, "light-a")["reason"]


def test_changed_policy_is_excluded_not_attributed_to_the_device():
    gen = scenario_power({"light-a": {"kind": "gradual", "total": 0.3}}, 28, random.Random(5))
    policy = lambda s, d, day: "pol-light-a:2" if (d == "light-a" and s == "evaluation" and day >= 5) else f"pol-{d}:1"  # noqa: E731
    data = ok(build_drift_request(14, 28, gen, policy=policy))
    light = dev(data, "light-a")
    assert light["excluded"]["evaluation"]["policy_changed"] == 23 * len(HOURS)
    assert light["status"] == "insufficient_history" and data["findings"] == []
    policy_all = lambda s, d, day: "pol-light-a:2" if (d == "light-a" and s == "evaluation") else f"pol-{d}:1"  # noqa: E731
    assert dev(ok(build_drift_request(14, 28, gen, policy=policy_all)), "light-a")["status"] == "unsupported_context"


def test_changed_operating_context_for_comfort_equipment_is_not_a_trend():
    def room(section, room_id, day, hour):
        temp = 25.0 if section == "reference" else 25.0 + 4.0 * day / 27  # evaluation drifts into hotter rooms
        return (temp, 5.0 if room_id == "room-a" else 0.0)

    data = ok(case(room=room))  # AC power follows temperature; no equipment change
    ac = dev(data, "ac-a")
    assert all(f["device_id"] != "ac-a" for f in data["findings"])
    assert ac["excluded"]["evaluation"].get("no_reference_for_context", 0) > 0
    assert ac["classification"] in (None, "stable")


def test_changing_sampled_hours_is_not_deterioration():
    # Evaluation samples morning hours (820 W) first, afternoon hours (1100 W) later: raw average
    # rises ~34 % but nothing changes within any hour context.
    hours = lambda s, d, day: (HOURS if s == "reference" or d != "ws-group" else (tuple(range(9, 13)) if day < 14 else tuple(range(13, 18))))  # noqa: E731
    data = ok(case(hours=hours))
    assert all(f["device_id"] != "ws-group" for f in data["findings"])
    assert dev(data, "ws-group")["classification"] == "stable"


def test_mixed_duty_observations_are_excluded():
    gen = scenario_power({"light-a": {"kind": "gradual", "total": 0.5}}, 28, random.Random(6))
    power = lambda s, d, day, h: ((gen(s, d, day, h)[0] * 0.5, 0.5) if (d == "light-a" and s == "evaluation") else gen(s, d, day, h))  # noqa: E731
    light = dev(ok(build_drift_request(14, 28, power)), "light-a")
    assert light["excluded"]["evaluation"] == {"mixed_duty": 28 * len(HOURS)}
    assert light["status"] == "no_comparable_observations"


def test_group_quantity_does_not_multiply_power():
    data = ok(case())
    devices = copy.deepcopy(DEVICES)
    next(d for d in devices if d["device_id"] == "ws-group")["quantity"] = 1
    other = ok(case(devices=devices))
    assert dev(data, "ws-group")["reference_level_w"] == dev(other, "ws-group")["reference_level_w"]
    assert 800 < dev(data, "ws-group")["reference_level_w"] < 1150


def test_insufficient_temporal_support_is_explicit():
    short_eval = ok(case(eval_days=7))
    assert short_eval["status"] == "insufficient_history"
    assert "needs 10 over 14 days" in dev(short_eval, "light-a")["reason"]
    short_ref = ok(case(ref_days=3))
    assert "reference has 3 supported days" in dev(short_ref, "light-a")["reason"]


def test_duplicate_readings_do_not_inflate_support():
    body = case({"light-a": {"kind": "gradual", "total": 0.25}})
    base = ok(body)
    dup = copy.deepcopy(body)
    dup["evaluation"]["device_intervals"] += copy.deepcopy(dup["evaluation"]["device_intervals"][:100])
    data = ok(dup)
    assert dev(data, "light-a")["support"] == dev(base, "light-a")["support"]
    assert "DUPLICATES_DEDUPED" in {w["code"] for w in data["warnings"]}


def test_reference_baseline_is_unaffected_by_evaluation_values():
    a = ok(case())
    b = ok(case({"light-a": {"kind": "offset", "size": 3.0}, "fridge-b": {"kind": "gradual", "total": 0.9}}))
    for d in ("light-a", "fridge-b"):
        assert dev(a, d)["reference_level_w"] == dev(b, d)["reference_level_w"]
        assert dev(a, d)["contexts_with_baseline"] == dev(b, d)["contexts_with_baseline"]


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(("mutate", "field", "status", "code"), [
    (lambda b: b["reference"]["window"].update(end_utc=b["evaluation"]["device_intervals"][9]["interval_end_utc"]), "reference.window.end_utc", 400, "VALIDATION_ERROR"),
    (lambda b: b["evaluation"]["device_intervals"][3].update(is_fault=True), "evaluation.device_intervals[3].is_fault", 400, "VALIDATION_ERROR"),
    (lambda b: b["evaluation"]["device_intervals"][0].update(device_id="dev-x"), "evaluation.device_intervals[0].device_id", 400, "VALIDATION_ERROR"),
    (lambda b: b.update(detector={"version": "excess-power-mad-v1"}), "detector.version", 400, "VALIDATION_ERROR"),
    (lambda b: b["evaluation"].update(device_intervals=[b["evaluation"]["device_intervals"][0]] * 2001), "evaluation.device_intervals", 413, "REQUEST_TOO_LARGE"),
    (lambda b: b["reference"].update(room_intervals=[b["reference"]["room_intervals"][0]] * 2001), "reference.room_intervals", 413, "REQUEST_TOO_LARGE"),
])
def test_invalid_requests_are_rejected(mutate, field, status, code):
    body = case()
    mutate(body)
    got, payload = post(body)
    assert (got, payload["error"]["code"], payload["error"]["field"]) == (status, code, field)


def test_conflicting_duplicates_and_non_finite_values_are_rejected():
    body = case()
    x = copy.deepcopy(body["reference"]["device_intervals"][0])
    x["avg_power_w"] = x["max_power_w"] = 71.0
    x["energy_kwh"] = 0.071
    body["reference"]["device_intervals"].append(x)
    status, payload = post(body)
    assert status == 400 and "Conflicting duplicate" in payload["error"]["message"]
    raw = json.dumps(case()).replace('"avg_rh_pct": 55.0', '"avg_rh_pct": Infinity', 1)
    assert post(raw)[0] == 400


def test_default_room_helper_is_deterministic():
    assert default_room("reference", "room-a", 0, 9) == default_room("evaluation", "room-a", 5, 9)
