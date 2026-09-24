"""POST /v1/forecast — statistical hourly baseline, validation, calendar semantics, holdout evaluation.
All histories here are small, generated in memory, and SYNTHETIC."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.forecast.baseline import horizon_bounds, slot
from app.forecast.evaluation import holdout, visible_history
from app.forecast.synthetic import synthetic_history
from app.main import app

client = TestClient(app)
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
H = timedelta(hours=1)


def fmt(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, tzinfo=IST)


def request(history: dict[datetime, float], origin: datetime, horizon: str = "next_24h", **extra) -> dict:
    body = {
        "contract_version": "1.0.1",
        "dataset_id": "ds-synthetic",
        "origin_utc": fmt(origin),
        "horizon": horizon,
        "history_hourly_kwh": [{"start_utc": fmt(t), "energy_kwh": v} for t, v in sorted(history.items())],
        "calendar": {"timezone": "Asia/Kolkata", "working_days_iso": [1, 2, 3, 4, 5], "open_local": "09:00", "close_local": "18:00"},
    }
    body.update(extra)
    return body


def post(body) -> tuple[int, dict]:
    res = client.post("/v1/forecast", content=body if isinstance(body, (str, bytes)) else json.dumps(body),
                      headers={"Content-Type": "application/json"})
    return res.status_code, res.json()


def ok(body) -> dict:
    status, payload = post(body)
    assert status == 200, payload
    return payload["data"]


def constant(start: datetime, hours: int, value: float) -> dict[datetime, float]:
    return {start.astimezone(UTC) + i * H: value for i in range(hours)}


ORIGIN = local(2026, 3, 2)  # Monday 00:00 IST = 2026-03-01T18:30:00Z


# ------------------------------------------------------------------ baseline behaviour


def test_constant_input_gives_consistent_hourly_energy_and_totals():
    hist = constant(ORIGIN - timedelta(days=14), 14 * 24, 1.25)
    d24 = ok(request(hist, ORIGIN, "next_24h"))
    assert len(d24["points"]) == 24 and all(p["energy_kwh"] == 1.25 for p in d24["points"])
    assert d24["total_energy_kwh"] == pytest.approx(30.0)
    assert d24["basis_counts"] == {"weekday_hour": 24, "day_class_hour": 0, "hour_of_day": 0}
    d7 = ok(request(hist, ORIGIN, "next_7d"))
    assert len(d7["points"]) == 168 and d7["total_energy_kwh"] == pytest.approx(210.0)
    assert d7["model_version"] is None and d7["baseline_version"] == "hourly-profile-median-v1"
    assert d7["method"] == "statistical_baseline" and d7["uncertainty"] == "unavailable"


def test_known_weekday_hour_pattern_is_preserved():
    hist = synthetic_history(ORIGIN - timedelta(days=28), 28, seed=1, noise=0.0)
    points = {p["start_utc"]: p["energy_kwh"] for p in ok(request(hist, ORIGIN, "next_7d"))["points"]}
    at = lambda day, hour: points[fmt(local(2026, 3, day, hour))]  # noqa: E731
    assert at(2, 10) == pytest.approx(5.85)  # Monday working hour (+0.4 Monday effect)
    assert at(3, 10) == pytest.approx(5.45)  # Tuesday working hour
    assert at(3, 13) == pytest.approx(3.95)  # lunch dip
    assert at(3, 8) == pytest.approx(0.45)  # before opening
    assert at(7, 10) == pytest.approx(0.45)  # Saturday


def test_missing_hours_are_not_treated_as_zero():
    thin = {t: v for i, (t, v) in enumerate(sorted(constant(ORIGIN - timedelta(days=21), 21 * 24, 2.0).items())) if i % 5 == 0}
    status, payload = post(request(thin, ORIGIN, "next_24h"))  # gaps do not count toward eligibility
    assert status == 422 and "got 101" in payload["error"]["message"]
    full = constant(ORIGIN - timedelta(days=60), 60 * 24, 2.0)
    # Keep only every 5th hour (80% missing, cycling through all local hours). If gaps
    # were zeros, every median would collapse to 0; the baseline must still return 2.0.
    sparse = {t: v for i, (t, v) in enumerate(sorted(full.items())) if i % 5 == 0}
    data = ok(request(sparse, ORIGIN, "next_24h"))
    assert all(p["energy_kwh"] == 2.0 for p in data["points"])
    cov = data["history_coverage"]
    assert cov["observed_hours"] == len(sparse) and cov["missing_hours"] == cov["span_hours"] - len(sparse) > 0
    assert "MISSING_HOURS" in [w["code"] for w in data["warnings"]]


def test_fallback_hierarchy_is_disclosed():
    # 8-day history ending at the origin: the origin's weekday appears once → day-class fallback.
    data = ok(request(constant(ORIGIN - timedelta(days=8), 8 * 24, 1.0), ORIGIN, "next_24h"))
    assert data["basis_counts"] == {"weekday_hour": 0, "day_class_hour": 24, "hour_of_day": 0}
    assert "FALLBACK_DAY_CLASS" in [w["code"] for w in data["warnings"]]
    # Weekends almost absent (one Sunday): a Saturday forecast falls back to hour-of-day.
    saturday = ORIGIN + timedelta(days=5)
    hist = {t: v for t, v in constant(saturday - timedelta(days=14), 14 * 24, 1.0).items()
            if t.astimezone(IST).isoweekday() <= 5 or t.astimezone(IST).date() == (ORIGIN - timedelta(days=1)).date()}
    data = ok(request(hist, saturday, "next_24h"))
    assert data["basis_counts"] == {"weekday_hour": 0, "day_class_hour": 0, "hour_of_day": 24}
    assert "FALLBACK_HOUR_OF_DAY" in [w["code"] for w in data["warnings"]]


def test_same_input_produces_the_same_result():
    body = request(synthetic_history(ORIGIN - timedelta(days=30), 30, seed=7), ORIGIN, "next_7d")
    first, second = ok(body), ok(body)
    assert first == second


def test_future_assumptions_are_recorded_but_do_not_change_the_forecast():
    hist = synthetic_history(ORIGIN - timedelta(days=21), 21, seed=3)
    plain = ok(request(hist, ORIGIN))
    with_assumptions = ok(request(hist, ORIGIN, future_assumptions={
        "schedule": {"policy_id": "pol-light-a", "version": 1, "kind": "lighting_schedule",
                     "rules": {"on_during_hours": True, "vacancy_grace_seconds": 300}},
        "environment": {"avg_temp_c": 35.0, "avg_rh_pct": 80.0}}))
    assert with_assumptions["points"] == plain["points"]
    note = next(w for w in with_assumptions["warnings"] if w["code"] == "INPUTS_NOT_USED")["message"]
    assert "future_assumptions.environment" in note and "future_assumptions.schedule" in note
    assert with_assumptions["assumptions_recorded"]["environment"] == {"avg_temp_c": 35.0, "avg_rh_pct": 80.0}


# ------------------------------------------------------------------ horizons & calendar


def test_next_24h_and_next_7d_boundaries():
    hist = constant(ORIGIN - timedelta(days=14), 14 * 24, 1.0)
    for horizon, hours in (("next_24h", 24), ("next_7d", 168)):
        data = ok(request(hist, ORIGIN, horizon))
        assert data["horizon_start_utc"] == fmt(ORIGIN) == data["points"][0]["start_utc"]
        assert data["horizon_end_utc"] == fmt(ORIGIN + hours * H)
        assert data["points"][-1]["start_utc"] == fmt(ORIGIN + (hours - 1) * H)
        assert len(data["points"]) == hours
        assert data["timezone"] == "Asia/Kolkata"


def test_utc_hour_grid_is_accepted_for_24h_like_example_b():
    origin = datetime(2026, 3, 2, 0, tzinfo=UTC)  # 05:30 IST, as in API.md Example B
    hist = constant(origin - timedelta(days=7), 7 * 24, 1.0)
    data = ok(request(hist, origin, "next_24h"))
    assert data["points"][0]["start_utc"] == "2026-03-02T00:00:00Z"


@pytest.mark.parametrize(("origin", "start", "end", "hours"), [
    (local(2026, 12, 16), "2026-12-31T18:30:00Z", "2027-01-31T18:30:00Z", 31 * 24),  # year rollover → January 2027
    (local(2027, 1, 10), "2027-01-31T18:30:00Z", "2027-02-28T18:30:00Z", 28 * 24),  # non-leap February
    (local(2028, 1, 10), "2028-01-31T18:30:00Z", "2028-02-29T18:30:00Z", 29 * 24),  # leap February
    (local(2026, 2, 1, 1), "2026-02-28T18:30:00Z", "2026-03-31T18:30:00Z", 31 * 24),  # UTC Jan 31, local Feb 1 → March
])
def test_next_calendar_month_is_the_complete_next_local_month(origin, start, end, hours):
    hist = constant(origin - timedelta(days=30), 30 * 24, 0.5)
    data = ok(request(hist, origin, "next_calendar_month"))
    assert (data["horizon_start_utc"], data["horizon_end_utc"], len(data["points"])) == (start, end, hours)
    assert data["points"][0]["start_utc"] == start and data["points"][-1]["start_utc"] == fmt(datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) - H)
    assert data["total_energy_kwh"] == pytest.approx(0.5 * hours)
    gap = next(w for w in data["warnings"] if w["code"] == "GAP_BEFORE_HORIZON")
    assert "no observations are invented" in gap["message"]


def test_next_calendar_month_requires_a_local_midnight_aligned_grid():
    origin = datetime(2026, 3, 2, 0, tzinfo=UTC)
    status, payload = post(request(constant(origin - timedelta(days=30), 30 * 24, 1.0), origin, "next_calendar_month"))
    assert status == 400 and payload["error"]["field"] == "origin_utc"
    assert "local midnight" in payload["error"]["message"]


def test_asia_kolkata_local_calendar_interpretation():
    # 2026-01-04T20:00Z is Sunday in UTC but Monday 01:30 in Asia/Kolkata.
    assert slot(datetime(2026, 1, 4, 20, tzinfo=UTC), IST, {1, 2, 3, 4, 5}) == (1, 1, "working")
    assert slot(datetime(2026, 1, 4, 18, 30, tzinfo=UTC), IST, {1, 2, 3, 4, 5}) == (1, 0, "working")  # Mon 00:00 local
    assert slot(datetime(2026, 1, 4, 18, 29, tzinfo=UTC), IST, {1, 2, 3, 4, 5})[0] == 7


def test_dst_observing_timezones_are_not_accepted():
    body = request(constant(ORIGIN - timedelta(days=7), 7 * 24, 1.0), ORIGIN)
    body["calendar"]["timezone"] = "Europe/London"
    status, payload = post(body)
    assert status == 400 and payload["error"]["field"] == "calendar.timezone"


# ------------------------------------------------------------------ eligibility & validation


def test_insufficient_history_fails_clearly():
    status, payload = post(request(constant(ORIGIN - timedelta(days=3), 72, 1.0), ORIGIN, "next_24h"))
    assert (status, payload["error"]["code"]) == (422, "INSUFFICIENT_DATA")
    assert "at least 168 observed history hours" in payload["error"]["message"]
    status, payload = post(request(constant(ORIGIN - timedelta(days=10), 240, 1.0), ORIGIN, "next_calendar_month"))
    assert status == 422 and "672" in payload["error"]["message"]
    # Enough hours, but local 02:00 never observed → that slot cannot be forecast.
    hist = {t: v for t, v in constant(ORIGIN - timedelta(days=10), 240, 1.0).items() if t.astimezone(IST).hour != 2}
    status, payload = post(request(hist, ORIGIN, "next_24h"))
    assert status == 422 and "02:00 local" in payload["error"]["message"]


def test_reference_fixture_scale_history_is_not_forecast():
    # The contract fixture covers two minutes; its whole energy as one hour is far below eligibility.
    status, payload = post(request({ORIGIN.astimezone(UTC) - H: 0.03}, ORIGIN))
    assert (status, payload["error"]["code"]) == (422, "INSUFFICIENT_DATA")


def test_oversize_history_returns_413():
    status, payload = post(request(constant(ORIGIN - timedelta(hours=2161), 2161, 1.0), ORIGIN))
    assert status == 413 and payload["error"]["code"] == "REQUEST_TOO_LARGE"
    assert ok(request(constant(ORIGIN - timedelta(hours=2160), 2160, 1.0), ORIGIN))["history_coverage"]["observed_hours"] == 2160


@pytest.mark.parametrize(("mutate", "field", "code"), [
    (lambda b: b["history_hourly_kwh"].append({"start_utc": b["origin_utc"], "energy_kwh": 1.0}), "history_hourly_kwh[168].start_utc", "VALIDATION_ERROR"),
    (lambda b: b["history_hourly_kwh"][5].update(start_utc="2026-02-23T00:00:00Z"), "history_hourly_kwh[5].start_utc", "VALIDATION_ERROR"),  # off-grid
    (lambda b: b["history_hourly_kwh"][5].update(energy_kwh=-0.1), "history_hourly_kwh[5].energy_kwh", "VALIDATION_ERROR"),
    (lambda b: b["history_hourly_kwh"][5].update(start_utc=b["history_hourly_kwh"][1]["start_utc"]), "history_hourly_kwh[5].start_utc", "VALIDATION_ERROR"),  # order
    (lambda b: b.update(origin_utc="2026-03-01T18:15:00Z"), "origin_utc", "VALIDATION_ERROR"),
    (lambda b: b.update(horizon="next_30d"), "horizon", "VALIDATION_ERROR"),
    (lambda b: b.update(contract_version="1.0.0"), "contract_version", "UNSUPPORTED_VERSION"),
    (lambda b: b["calendar"].pop("timezone"), "calendar.timezone", "VALIDATION_ERROR"),
    (lambda b: b["calendar"].update(working_days_iso=[1, 1]), "calendar.working_days_iso", "VALIDATION_ERROR"),
    (lambda b: b["calendar"].update(close_local="09:00"), "calendar.close_local", "VALIDATION_ERROR"),
    (lambda b: b.update(model={"version": "baseline-v1"}), "model.version", "VALIDATION_ERROR"),
    (lambda b: b.update(tariff_inr_per_kwh=10), "tariff_inr_per_kwh", "VALIDATION_ERROR"),
    (lambda b: b["history_hourly_kwh"][3].update(fault_active=True), "history_hourly_kwh[3].fault_active", "VALIDATION_ERROR"),
])
def test_invalid_requests_are_rejected(mutate, field, code):
    body = request(constant(ORIGIN - timedelta(days=7), 168, 1.0), ORIGIN)
    mutate(body)
    status, payload = post(body)
    assert status == 400, payload
    assert (payload["error"]["code"], payload["error"]["field"]) == (code, field)


def test_non_finite_json_numbers_are_rejected():
    body = json.dumps(request(constant(ORIGIN - timedelta(days=7), 168, 1.0), ORIGIN)).replace('"energy_kwh": 1.0', '"energy_kwh": NaN', 1)
    status, payload = post(body)
    assert status == 400 and "non-finite" in payload["error"]["message"]


def test_duplicates_identical_deduplicated_conflicting_rejected():
    body = request(constant(ORIGIN - timedelta(days=7), 168, 1.0), ORIGIN)
    body["history_hourly_kwh"].insert(1, dict(body["history_hourly_kwh"][0]))
    data = ok(body)
    assert data["history_coverage"]["duplicates_deduped"] == 1
    body["history_hourly_kwh"][1]["energy_kwh"] = 9.0
    status, payload = post(body)
    assert status == 400 and "Conflicting duplicate" in payload["error"]["message"]


def test_model_version_matching_the_baseline_is_accepted():
    body = request(constant(ORIGIN - timedelta(days=7), 168, 1.0), ORIGIN, model={"version": "hourly-profile-median-v1"})
    assert ok(body)["baseline_version"] == "hourly-profile-median-v1"


# ------------------------------------------------------------------ holdout evaluation


def test_holdout_cannot_see_future_observations():
    hist = synthetic_history(local(2026, 1, 5), 42, seed=11)
    cutoff = local(2026, 2, 9).astimezone(UTC)
    visible = visible_history(hist, cutoff)
    assert max(visible) + H <= cutoff
    poisoned = {t: (v if t + H <= cutoff else 1e6) for t, v in hist.items()}  # absurd future values
    a = holdout(hist, cutoff, "next_7d", IST, {1, 2, 3, 4, 5})
    b = holdout(poisoned, cutoff, "next_7d", IST, {1, 2, 3, 4, 5})
    # Predictions must not change; only the scores against the (poisoned) truth differ.
    assert a["baseline"].hours_scored == b["baseline"].hours_scored == 168
    assert b["baseline"].aggregate_error_kwh < -1e7 and b["repeat_last_day"].aggregate_error_kwh < -1e7
    assert a["baseline"].mae_kwh_per_hour < 1.0


def test_holdout_compares_baseline_with_repeat_last_day_on_the_same_hours():
    hist = synthetic_history(local(2026, 1, 5), 42, seed=12)
    scores = holdout(hist, local(2026, 2, 9).astimezone(UTC), "next_7d", IST, {1, 2, 3, 4, 5})
    assert scores["baseline"].hours_scored == scores["repeat_last_day"].hours_scored == 168
    assert scores["baseline"].mae_kwh_per_hour >= 0 and scores["repeat_last_day"].mae_kwh_per_hour >= 0


def test_horizon_bounds_helper_matches_contract_month_semantics():
    hz = horizon_bounds("next_calendar_month", local(2026, 12, 31, 23).astimezone(UTC), IST)
    assert (fmt(hz.start), fmt(hz.end)) == ("2026-12-31T18:30:00Z", "2027-01-31T18:30:00Z")
