"""P016 offline training workflow: input validation, leakage, splits, determinism,
bundles and shared scoring. Small SYNTHETIC series and tiny models only."""

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.training import evaluate as ev
from app.training.candidate import (
    CandidateUnavailable, load_bundle, predict_horizon, save_bundle, train,
)
from app.training.features import FEATURE_NAMES, SortedHistory, features_for, origin_context
from app.training.input import TrainingInputError, fmt_utc, load_training_input, parse_training_input, to_document
from app.training.synthetic import IST, generate

TINY = {"max_iter": 15}
UTC = timezone.utc


@pytest.fixture(scope="module")
def small():
    return generate("trend_regime", 7, days=60)


def local(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, tzinfo=IST).astimezone(UTC)


# ------------------------------------------------------------------ input format


def base_doc() -> dict:
    return {
        "format": "nexyra-hourly-training-v1", "series_id": "s1", "timezone": "Asia/Kolkata",
        "calendar": {"working_days_iso": [1, 2, 3, 4, 5]},
        "provenance": {"synthetic": True, "source": "test", "description": "SYNTHETIC test series"},
        "points": [{"start_utc": "2026-01-01T18:30:00Z", "energy_kwh": 1.0}, {"start_utc": "2026-01-01T19:30:00Z", "energy_kwh": 2.0}],
    }


@pytest.mark.parametrize(("mutate", "match"), [
    (lambda d: d["points"].append({"start_utc": "2026-01-01T18:30:00Z", "energy_kwh": 9.0}), "conflicting duplicate"),
    (lambda d: d["points"][0].update(energy_kwh=-1.0), "greater than or equal"),
    (lambda d: d["points"][0].update(start_utc="2026-02-30T18:30:00Z"), "not a real UTC timestamp"),
    (lambda d: d["points"][0].update(start_utc="2026-01-01T18:45:00Z"), "full hour"),
    (lambda d: d["points"].append({"start_utc": "2026-01-01T21:00:00Z", "energy_kwh": 1.0}), "mixed hourly grids"),
    (lambda d: d.update(timezone="Europe/London"), "not supported"),
    (lambda d: d["points"][1].update(fault_label="x"), "forbidden"),
    (lambda d: d.update(format="csv"), "format"),
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d["provenance"].pop("synthetic"), "provenance.synthetic"),
])
def test_invalid_training_input_is_rejected(mutate, match):
    doc = base_doc()
    mutate(doc)
    with pytest.raises(TrainingInputError, match=match):
        parse_training_input(doc)


def test_identical_duplicates_deduplicated_and_missing_hours_stay_missing(tmp_path):
    doc = base_doc()
    doc["points"].append(dict(doc["points"][0]))
    doc["points"].append({"start_utc": "2026-01-01T22:30:00Z", "energy_kwh": 3.0})  # 2 missing hours in between
    series = parse_training_input(doc)
    assert series.duplicates_deduped == 1
    assert len(series.history) == 3  # no zero-filled hours
    path = tmp_path / "in.json"
    path.write_text(json.dumps(to_document(series)).replace("3.0", "NaN"), encoding="utf-8")
    with pytest.raises(TrainingInputError, match="non-finite"):
        load_training_input(path)


def test_missing_history_gives_nan_features_not_zero():
    history = {local(2026, 1, 5, h): 2.0 for h in range(9, 12)}  # only three hours observed
    ctx = origin_context(SortedHistory(history), local(2026, 1, 6), IST, {1, 2, 3, 4, 5})
    f = dict(zip(FEATURE_NAMES, features_for(ctx, local(2026, 1, 6, 3), IST, {1, 2, 3, 4, 5})))
    assert math.isnan(f["profile_weekday_hour"]) and math.isnan(f["last_obs_same_hour"])
    assert math.isnan(f["mean_last_7d"]) and math.isnan(f["mean_last_28d"])
    assert f["support_weekday_hour"] == 0.0  # a count, not a missing value


# ------------------------------------------------------------------ leakage & multi-step availability


def test_features_never_see_observations_at_or_after_the_origin(small):
    origin = small.start + timedelta(days=30)
    origin = origin.replace(minute=30)  # local midnight grid is :30Z
    poisoned = {t: (v if t + timedelta(hours=1) <= origin else 1e6) for t, v in small.history.items()}
    hours = [origin + timedelta(hours=k) for k in range(0, 45 * 24, 7)]  # deep into a month-length horizon
    a = origin_context(SortedHistory(small.history), origin, IST, small.working_days)
    b = origin_context(SortedHistory(poisoned), origin, IST, small.working_days)
    for t in hours:
        assert features_for(a, t, IST, small.working_days) == pytest.approx(features_for(b, t, IST, small.working_days), nan_ok=True)
    leads = [features_for(a, t, IST, small.working_days)[FEATURE_NAMES.index("lead_days")] for t in hours]
    assert leads == sorted(leads) and leads[0] == 0 and leads[-1] >= 40


def test_training_ignores_everything_after_the_cutoff(small):
    cutoff = small.start + timedelta(days=40)
    poisoned = generate("trend_regime", 7, days=60)
    poisoned.history = {t: (v if t + timedelta(hours=1) <= cutoff else 1e6) for t, v in small.history.items()}
    a = train(small, cutoff, "hgb-mae-small", seed=3, params_override=TINY)
    b = train(poisoned, cutoff, "hgb-mae-small", seed=3, params_override=TINY)
    assert a.training_rows == b.training_rows
    origin = cutoff  # forecast from the cutoff, with visible history identical in both
    assert predict_horizon(a, small.history, origin, "next_7d") == predict_horizon(b, poisoned.history, origin, "next_7d")


def test_candidate_requires_minimum_visible_history(small):
    cand = train(small, small.start + timedelta(days=30), "hgb-mae-small", seed=0, params_override=TINY)
    with pytest.raises(CandidateUnavailable):
        predict_horizon(cand, small.history, small.start + timedelta(days=3), "next_24h")


# ------------------------------------------------------------------ determinism & bundles


def test_training_is_deterministic_for_fixed_inputs_and_seed(small):
    cutoff = small.start + timedelta(days=40)
    origin = cutoff
    p1 = predict_horizon(train(small, cutoff, "hgb-mae-small", seed=5, params_override=TINY), small.history, origin, "next_7d")
    p2 = predict_horizon(train(small, cutoff, "hgb-mae-small", seed=5, params_override=TINY), small.history, origin, "next_7d")
    assert p1 == p2
    assert all(v >= 0 for v in p1.values())  # documented clip


def test_save_reload_predictions_are_identical_and_tampering_is_refused(small, tmp_path):
    cand = train(small, small.start + timedelta(days=40), "hgb-mae-small", seed=1, params_override=TINY)
    bundle = save_bundle(cand, tmp_path / "bundle", evaluation={"note": "test"})
    meta = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    for key in ("model_id", "feature_version", "training_cutoff_utc", "timezone", "seed", "dependency_versions", "provenance", "model_sha256"):
        assert key in meta
    assert "NOT deployed" in meta["status"] and meta["provenance"]["synthetic"] is True
    origin = small.start + timedelta(days=45)
    assert predict_horizon(load_bundle(bundle), small.history, origin, "next_calendar_month") == \
        predict_horizon(cand, small.history, origin, "next_calendar_month")
    (bundle / "model.joblib").write_bytes((bundle / "model.joblib").read_bytes() + b"x")
    with pytest.raises(ValueError, match="SHA-256"):
        load_bundle(bundle)
    meta["feature_version"] = "other"
    (bundle / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="feature version"):
        load_bundle(bundle)


# ------------------------------------------------------------------ splits & scoring


def test_split_boundaries_and_origin_windows():
    series = generate("weekly_stable", 1)  # default 430 days
    s = ev.splits_for(series)
    assert (s.train_end - s.start, s.validation_end - s.start) == (timedelta(days=280), timedelta(days=350))
    assert s.start.astimezone(IST).hour == 0
    for horizon in ev.HORIZONS:
        for a, b in ((s.train_end, s.validation_end), (s.validation_end, s.test_end)):
            origins = ev.eval_origins(horizon, a, b, IST)
            assert origins, horizon
            for o in origins:
                end = ev.horizon_bounds(horizon, o, IST).end
                assert a <= o and end <= b  # validation never reaches test; test targets end by test_end


def test_selection_is_frozen_before_any_test_forecast(monkeypatch, small):
    calls = []

    class Dummy:
        training_rows, fit_seconds, feature_build_seconds = 1, 0.0, 0.0

    def fake_train(series, cutoff, name, seed, override=None, trace=None):
        calls.append(("train", name, cutoff))
        return Dummy()

    def fake_window(series, a, b, predictors, trace=None):
        calls.append(("window", a, b))
        mae = {"hgb-mae-small": 0.3, "hgb-mse-small": 0.2, "hgb-mae-medium": 0.25}
        name = [c for c in calls if c[0] == "train"][-1][1]
        return {h: {"origins_eligible": 1, "methods": {"candidate": {"mae_kwh_per_hour": mae[name]}}} for h in ev.HORIZONS}

    monkeypatch.setattr(ev, "train", fake_train)
    monkeypatch.setattr(ev, "evaluate_window", fake_window)
    monkeypatch.setattr(ev, "make_predictors", lambda series, cand: {})
    report, _ = ev.run_experiment(generate("weekly_stable", 1), seed=0)
    s = ev.splits_for(generate("weekly_stable", 1))
    assert report["selection"]["selected_config"] == "hgb-mse-small"
    trains = [c for c in calls if c[0] == "train"]
    windows = [c for c in calls if c[0] == "window"]
    assert all(c[2] == s.train_end for c in trains[:3]) and trains[3] == ("train", "hgb-mse-small", s.validation_end)
    assert all(w[1:] == (s.train_end, s.validation_end) for w in windows[:3]) and windows[3][1:] == (s.validation_end, s.test_end)
    assert calls.index(windows[3]) > calls.index(trains[3]) > calls.index(windows[2])  # test only after freezing + refit


def test_methods_are_scored_on_identical_timestamps_and_failures_exclude_origins(small):
    start = small.start + timedelta(days=20)
    end = start + timedelta(days=3)

    def full(o, h):
        return {t: 1.0 for t in ev.horizon_bounds(h, o, IST).hours}

    def partial(o, h):  # predicts only even hours
        return {t: 2.0 for t in ev.horizon_bounds(h, o, IST).hours if t.astimezone(IST).hour % 2 == 0}

    def flaky(o, h):
        if o.astimezone(IST).day % 2 == 0:
            raise CandidateUnavailable("not enough history")
        return full(o, h)

    rep = ev.evaluate_window(small, start, end, {"a": full, "b": partial, "c": flaky})["next_24h"]
    assert rep["failures"]["c"] == rep["origins"] - rep["origins_eligible"] > 0
    assert rep["failures"]["a"] == rep["failures"]["b"] == 0
    # Common scored hours = observed ∩ even hours on eligible origins, the same for every method.
    assert rep["hours_scored_common"] <= rep["hours_observed"] // 2 + rep["origins_eligible"]
    assert rep["hours_expected"] == 24 * rep["origins"]
    maes = {m: rep["methods"][m]["mae_kwh_per_hour"] for m in "abc"}
    assert maes["a"] == maes["c"]  # identical predictions on identical timestamps give identical MAE


def test_cli_generate_validate_roundtrip(tmp_path, capsys):
    from app.training.cli import main

    out = tmp_path / "data" / "s.json"
    main(["generate", "--scenario", "seasonal_ac", "--seed", "4", "--days", "20", "--out", str(out)])
    main(["validate", "--input", str(out)])
    summary = json.loads(capsys.readouterr().out.split("\n}\n", 1)[1])
    assert summary["valid"] is True and summary["provenance"]["synthetic"] is True
    assert summary["observed_hours"] + summary["missing_hours"] == 20 * 24
    assert fmt_utc(load_training_input(out).start) == "2025-10-05T18:30:00Z"


# ------------------------------------------------------------------ P021: target boundaries (not only origins)


def test_training_origins_before_the_cutoff_never_contribute_targets_after_it(small):
    from app.training.candidate import build_training_rows

    cutoff = small.start + timedelta(days=40)
    rows: list = []
    build_training_rows(small, cutoff, trace=rows)
    assert rows and all(t + timedelta(hours=1) <= cutoff for _, t in rows)
    # Origins whose month-scale lead window (62 d) crosses the cutoff do contribute, but only truncated rows.
    crossing = {o for o, _ in rows if o + timedelta(days=62) > cutoff}
    assert crossing
    for o in crossing:
        month_end = ev.horizon_bounds("next_calendar_month", o, IST).end
        if month_end > cutoff:
            assert max(t for oo, t in rows if oo == o) + timedelta(hours=1) <= cutoff < month_end


def test_month_origin_whose_month_crosses_the_window_end_is_excluded_from_scoring(small):
    a, b = local(2025, 10, 20), local(2025, 11, 20)  # Nov 15 origin → December crosses b
    assert ev.eval_origins("next_calendar_month", a, b, IST) == []
    a2, b2 = local(2025, 10, 10), local(2025, 12, 1)  # Oct 15 → November ends exactly at b2: kept; Nov 15 excluded
    assert ev.eval_origins("next_calendar_month", a2, b2, IST) == [local(2025, 10, 15)]
    trace: list = []

    def flat(o, h):
        return {t: 1.0 for t in ev.horizon_bounds(h, o, IST).hours}

    ev.evaluate_window(small, a2, b2, {"x": flat}, trace=trace)
    assert trace and all(end <= b2 for _, _, end, _, _ in trace)
    assert all(t + timedelta(hours=1) <= b2 for *_, scored in trace for t in scored)


def test_test_period_outcomes_cannot_change_configuration_selection(monkeypatch):
    # Shortened split for speed (same code path): train <= day 60, validation origins days 60-110, test after.
    monkeypatch.setattr(ev, "TRAIN_DAYS", 60)
    monkeypatch.setattr(ev, "VALIDATION_END_DAYS", 110)
    clean = generate("seasonal_ac", 11, days=150)
    s = ev.splits_for(clean)
    poisoned = generate("seasonal_ac", 11, days=150)
    poisoned.history = {t: (v if t + timedelta(hours=1) <= s.validation_end else 1e6) for t, v in clean.history.items()}
    tiny = {"max_iter": 10}
    ta: dict = {}
    tb: dict = {}
    ra, _ = ev.run_experiment(clean, 0, params_override=tiny, trace=ta)
    rb, _ = ev.run_experiment(poisoned, 0, params_override=tiny, trace=tb)
    # Selection inputs, the frozen choice and the final refit's examples are identical...
    assert {n: v["score_mean_candidate_mae"] for n, v in ra["validation"].items()} == \
        {n: v["score_mean_candidate_mae"] for n, v in rb["validation"].items()}
    assert ra["selection"] == rb["selection"]
    assert ta["fit_initial"] == tb["fit_initial"] and ta["fit_final"] == tb["fit_final"]
    # ...while the test scores do see the poisoned outcomes.
    assert rb["test"]["next_24h"]["methods"]["candidate"]["mae_kwh_per_hour"] > 1e5
    # Long horizons cannot bypass: the Dec 15 validation origin (January crosses test start) was never scored.
    crossing = local(2025, 12, 15)
    assert ev.horizon_bounds("next_calendar_month", crossing, IST).end > s.validation_end
    assert all(o != crossing for rows in ta["validation"].values() for h, o, *_ in rows if h == "next_calendar_month")
    assert any(o == crossing for rows in ta["validation"].values() for h, o, *_ in rows if h == "next_24h")  # same origin, 24 h fits
    assert all(end <= s.validation_end for rows in ta["validation"].values() for _, _, end, _, _ in rows)
