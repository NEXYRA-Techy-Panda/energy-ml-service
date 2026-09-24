"""Temporal evaluation: repeat-last-day vs the P013 baseline vs the trained candidate.

Splits (relative to the first local midnight of the series; fixed, not tuned):
  train      : hours ending at or before T1 = start + 280 d
  validation : forecast origins in [T1, T2 = start + 350 d); targets < T2
  test       : forecast origins in [T2, end); targets < end (untouched until
               the configuration is frozen)

Protocol per series and seed:
1. For each predetermined config, train on hours ending <= T1; forecast the
   validation origins; select the config with the lowest mean validation
   MAE across horizons (ties → first listed). The selection is recorded and
   FROZEN before any test forecast is made.
2. Refit the frozen config on all hours ending <= T2 (train ∪ validation,
   all earlier than the test period).
3. Forecast every test origin with all three methods.

Scoring: an origin is ELIGIBLE only if all three methods produce a forecast
(failures are counted per method). Metrics use COMMON SCORED HOURS: horizon
hours that were observed AND predicted by every method. Reported: hourly
MAE (kWh), energy error over common scored hours (predicted − actual, kWh;
not a complete-horizon total when hours are missing), expected/observed/
scored hour counts, failures, and timing.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from ..errors import ApiError
from ..forecast.baseline import forecast as baseline_forecast
from ..forecast.baseline import horizon_bounds
from ..forecast.constants import BASELINE_VERSION
from ..forecast.evaluation import repeat_last_day, visible_history
from .candidate import CONFIGS, Candidate, CandidateUnavailable, local_midnights, predict_context, train
from .features import FEATURE_VERSION, SortedHistory, origin_context
from .input import TrainingSeries, fmt_utc

TRAIN_DAYS = 280
VALIDATION_END_DAYS = 350
HORIZONS = ("next_24h", "next_7d", "next_calendar_month")
METHODS = ("repeat_last_day", "baseline", "candidate")
Predictor = Callable[[datetime, str], dict[datetime, float]]


@dataclass(frozen=True)
class Splits:
    start: datetime
    train_end: datetime
    validation_end: datetime
    test_end: datetime

    def as_dict(self) -> dict:
        return {"series_start_utc": fmt_utc(self.start), "train_end_utc": fmt_utc(self.train_end),
                "validation_end_utc": fmt_utc(self.validation_end), "test_end_utc": fmt_utc(self.test_end),
                "rule": "train: hours ending <= train_end; validation origins in [train_end, validation_end), targets < validation_end; "
                        "test origins in [validation_end, test_end), targets < test_end"}


def splits_for(series: TrainingSeries) -> Splits:
    start = local_midnights(series.start, series.start + timedelta(days=1), series.tz)[0]
    return Splits(start, start + timedelta(days=TRAIN_DAYS), start + timedelta(days=VALIDATION_END_DAYS), series.end)


def eval_origins(horizon: str, a: datetime, b: datetime, tz) -> list[datetime]:
    out = []
    for o in local_midnights(a, b, tz):
        local = o.astimezone(tz)
        if horizon == "next_7d" and local.isoweekday() != 1:
            continue
        if horizon == "next_calendar_month" and local.day != 15:
            continue
        if horizon_bounds(horizon, o, tz).end <= b:
            out.append(o)
    return out


def make_predictors(series: TrainingSeries, candidate: Candidate | None) -> dict[str, Predictor]:
    hist = SortedHistory(series.history)
    tz, wd = series.tz, series.working_days

    def rld(origin: datetime, horizon: str) -> dict[datetime, float]:
        visible = visible_history(series.history, origin)
        if not visible:
            raise CandidateUnavailable("no visible history")
        return repeat_last_day(visible, horizon_bounds(horizon, origin, tz).hours)

    def base(origin: datetime, horizon: str) -> dict[datetime, float]:
        visible = visible_history(series.history, origin)
        try:
            return {p.start: p.energy_kwh for p in baseline_forecast(visible, horizon_bounds(horizon, origin, tz), tz, wd, horizon)}
        except ApiError as exc:
            raise CandidateUnavailable(exc.message) from None

    predictors: dict[str, Predictor] = {"repeat_last_day": rld, "baseline": base}
    if candidate is not None:
        def cand(origin: datetime, horizon: str) -> dict[datetime, float]:
            ctx = origin_context(hist, origin, tz, wd)
            return predict_context(candidate, ctx, horizon_bounds(horizon, origin, tz).hours, tz, wd)

        predictors["candidate"] = cand
    return predictors


def evaluate_window(series: TrainingSeries, a: datetime, b: datetime, predictors: dict[str, Predictor],
                    trace: list | None = None) -> dict:
    """`trace` (optional, audit only) receives (horizon, origin, horizon_end, eligible, scored target starts)."""
    tz = series.tz
    report = {}
    for horizon in HORIZONS:
        origins = eval_origins(horizon, a, b, tz)
        failures = {m: 0 for m in predictors}
        failure_notes: list[str] = []
        seconds = {m: 0.0 for m in predictors}
        abs_err = {m: 0.0 for m in predictors}
        energy_err: dict[str, list[float]] = {m: [] for m in predictors}
        expected_all = expected_eligible = observed = scored = eligible = 0
        for o in origins:
            hours = horizon_bounds(horizon, o, tz).hours
            expected_all += len(hours)
            preds, ok = {}, True
            for m, predict in predictors.items():
                t0 = time.perf_counter()
                try:
                    preds[m] = predict(o, horizon)
                except CandidateUnavailable as exc:
                    failures[m] += 1
                    failure_notes.append(f"{fmt_utc(o)} {m}: {exc}")
                    ok = False
                seconds[m] += time.perf_counter() - t0
            if not ok:
                if trace is not None:
                    trace.append((horizon, o, horizon_bounds(horizon, o, tz).end, False, []))
                continue
            eligible += 1
            expected_eligible += len(hours)
            actual = {t: series.history[t] for t in hours if t in series.history}
            observed += len(actual)
            common = [t for t in actual if all(t in p for p in preds.values())]
            scored += len(common)
            if trace is not None:
                trace.append((horizon, o, horizon_bounds(horizon, o, tz).end, True, common))
            for m, p in preds.items():
                errors = [p[t] - actual[t] for t in common]
                abs_err[m] += sum(abs(e) for e in errors)
                energy_err[m].append(sum(errors))
        report[horizon] = {
            "origins": len(origins),
            "origins_eligible": eligible,
            "failures": failures,
            "failure_notes": failure_notes[:10],
            "hours_expected": expected_all,
            "hours_expected_eligible_origins": expected_eligible,
            "hours_observed": observed,
            "hours_scored_common": scored,
            "methods": {
                m: {
                    "mae_kwh_per_hour": abs_err[m] / scored if scored else None,
                    "energy_error_over_common_scored_hours_kwh": {
                        "mean_abs_per_origin": sum(abs(e) for e in energy_err[m]) / len(energy_err[m]) if energy_err[m] else None,
                        "mean_per_origin": sum(energy_err[m]) / len(energy_err[m]) if energy_err[m] else None,
                    },
                    "inference_ms_per_origin": 1000 * seconds[m] / len(origins) if origins else None,
                } for m in predictors
            },
        }
    return report


def _selection_score(window_report: dict) -> float | None:
    maes = [h["methods"]["candidate"]["mae_kwh_per_hour"] for h in window_report.values()
            if h["origins_eligible"] and h["methods"]["candidate"]["mae_kwh_per_hour"] is not None]
    return sum(maes) / len(maes) if maes else None


def run_experiment(series: TrainingSeries, seed: int, params_override: dict | None = None,
                   configs: tuple[str, ...] | None = None, trace: dict | None = None) -> tuple[dict, Candidate]:
    """`trace` (optional, audit only) collects the actual examples of every phase:
    fit_initial[config], validation[config], fit_final, test."""
    splits = splits_for(series)
    names = configs or tuple(CONFIGS)
    t = trace if trace is not None else None
    if t is not None:
        t.update({"fit_initial": {}, "validation": {}, "fit_final": [], "test": []})

    # 1) Validation-based selection (models see only hours ending <= train_end).
    validation = {}
    for name in names:
        cand = train(series, splits.train_end, name, seed, params_override,
                     trace=t["fit_initial"].setdefault(name, []) if t is not None else None)
        rep = evaluate_window(series, splits.train_end, splits.validation_end, make_predictors(series, cand),
                              trace=t["validation"].setdefault(name, []) if t is not None else None)
        validation[name] = {"score_mean_candidate_mae": _selection_score(rep), "fit_seconds": cand.fit_seconds,
                            "training_rows": cand.training_rows, "report": rep}
    scored = [(v["score_mean_candidate_mae"], i, n) for i, (n, v) in enumerate(validation.items()) if v["score_mean_candidate_mae"] is not None]
    selected = min(scored)[2] if scored else names[0]
    selection = {"selected_config": selected, "frozen_before_test": True,
                 "rule": "lowest mean validation candidate MAE across horizons; ties -> first listed"}

    # 2) Refit the frozen config on everything before the test period; 3) test.
    final = train(series, splits.validation_end, selected, seed, params_override,
                  trace=t["fit_final"] if t is not None else None)
    test = evaluate_window(series, splits.validation_end, splits.test_end, make_predictors(series, final),
                           trace=t["test"] if t is not None else None)
    report = {
        "series_id": series.series_id,
        "provenance": series.provenance,
        "seed": seed,
        "baseline_version": BASELINE_VERSION,
        "feature_version": FEATURE_VERSION,
        "splits": splits.as_dict(),
        "configs": {n: {**CONFIGS[n], **(params_override or {})} for n in names},
        "validation": validation,
        "selection": selection,
        "final_model": {"config": selected, "training_cutoff_utc": fmt_utc(splits.validation_end),
                        "training_rows": final.training_rows, "fit_seconds": round(final.fit_seconds, 3),
                        "feature_build_seconds": round(final.feature_build_seconds, 3)},
        "test": test,
    }
    return report, final
