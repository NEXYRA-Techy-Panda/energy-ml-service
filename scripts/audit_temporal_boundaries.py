"""P021 temporal-boundary audit of the P016 evaluation (offline, SYNTHETIC data).

Runs the real run_experiment (actual configs) with tracing enabled and reports,
per phase (initial fit, validation/selection, final refit, test) and horizon,
the earliest/latest origin, earliest/latest target, latest target END, the
relevant cutoff, counts, and whether each invariant holds. Also checks that
every traced origin's feature window ends at or before the origin, and lists
month-horizon origins excluded because their month would cross a boundary.

Run: .venv\\Scripts\\python.exe scripts\\audit_temporal_boundaries.py [--scenario trend_regime --seed 101 --out FILE]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.forecast.baseline import horizon_bounds  # noqa: E402
from app.training.candidate import local_midnights  # noqa: E402
from app.training.evaluate import HORIZONS, run_experiment, splits_for  # noqa: E402
from app.training.features import SortedHistory  # noqa: E402
from app.training.input import fmt_utc  # noqa: E402
from app.training.synthetic import generate  # noqa: E402

HOUR = timedelta(hours=1)


def fit_phase(rows: list[tuple[datetime, datetime]], cutoff: datetime) -> dict:
    origins = sorted({o for o, _ in rows})
    targets = sorted(t for _, t in rows)
    lead_h = [(t - o) // HOUR for o, t in rows]
    crossing = sorted({o for o in origins if o + timedelta(days=62) > cutoff})
    return {
        "cutoff_utc": fmt_utc(cutoff),
        "rows": len(rows),
        "origins": len(origins),
        "earliest_origin_utc": fmt_utc(origins[0]), "latest_origin_utc": fmt_utc(origins[-1]),
        "earliest_target_start_utc": fmt_utc(targets[0]), "latest_target_start_utc": fmt_utc(targets[-1]),
        "latest_target_end_utc": fmt_utc(targets[-1] + HOUR),
        "rows_by_lead": {"lead_lt_24h": sum(1 for h in lead_h if h < 24), "lead_24h_to_7d": sum(1 for h in lead_h if 24 <= h < 168),
                         "lead_ge_7d": sum(1 for h in lead_h if h >= 168), "max_lead_hours": max(lead_h)},
        "origins_whose_62d_window_crosses_cutoff": len(crossing),
        "rows_from_those_origins": sum(1 for o, _ in rows if o in set(crossing)),
        "invariant_all_target_ends_le_cutoff": all(t + HOUR <= cutoff for t in targets),
    }


def window_phase(trace: list, a: datetime, b: datetime, horizon: str) -> dict:
    items = [x for x in trace if x[0] == horizon]
    origins = [x[1] for x in items]
    ends = [x[2] for x in items]
    scored = sorted(t for x in items for t in x[4])
    return {
        "window": [fmt_utc(a), fmt_utc(b)],
        "origins": len(origins), "eligible": sum(1 for x in items if x[3]),
        "earliest_origin_utc": fmt_utc(min(origins)) if origins else None,
        "latest_origin_utc": fmt_utc(max(origins)) if origins else None,
        "latest_horizon_end_utc": fmt_utc(max(ends)) if ends else None,
        "earliest_scored_target_start_utc": fmt_utc(scored[0]) if scored else None,
        "latest_scored_target_start_utc": fmt_utc(scored[-1]) if scored else None,
        "latest_scored_target_end_utc": fmt_utc(scored[-1] + HOUR) if scored else None,
        "scored_targets": len(scored),
        "invariant_origins_ge_window_start": all(o >= a for o in origins),
        "invariant_full_horizon_end_le_window_end": all(e <= b for e in ends),
        "invariant_scored_target_ends_le_window_end": all(t + HOUR <= b for t in scored),
    }


def excluded_month_origins(a: datetime, b: datetime, tz) -> list[dict]:
    out = []
    for o in local_midnights(a, b, tz):
        if o.astimezone(tz).day == 15:
            hz = horizon_bounds("next_calendar_month", o, tz)
            if hz.end > b:
                out.append({"origin_utc": fmt_utc(o), "month_end_utc": fmt_utc(hz.end), "window_end_utc": fmt_utc(b), "excluded": True})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="trend_regime")
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--out", default="artifacts/reports/p021-boundary-audit.json")
    a = ap.parse_args()

    series = generate(a.scenario, a.seed)
    sp = splits_for(series)
    trace: dict = {}
    report, _ = run_experiment(series, seed=0, trace=trace)

    fits = trace["fit_initial"]
    first = next(iter(fits.values()))
    audit = {
        "series_id": series.series_id, "synthetic": True, "splits": sp.as_dict(),
        "selected_config": report["selection"]["selected_config"],
        "A_initial_fit": fit_phase(first, sp.train_end),
        "A_identical_rows_for_every_config": all(rows == first for rows in fits.values()),
        "B_validation": {h: window_phase(next(iter(trace["validation"].values())), sp.train_end, sp.validation_end, h) for h in HORIZONS},
        "B_identical_origins_and_targets_for_every_config": all(v == next(iter(trace["validation"].values())) for v in trace["validation"].values()),
        "B_selection_inputs": {n: v["score_mean_candidate_mae"] for n, v in report["validation"].items()},
        "C_final_refit": fit_phase(trace["fit_final"], sp.validation_end),
        "D_test": {h: window_phase(trace["test"], sp.validation_end, sp.test_end, h) for h in HORIZONS},
        "excluded_month_origins": {
            "validation": excluded_month_origins(sp.train_end, sp.validation_end, series.tz),
            "test": excluded_month_origins(sp.validation_end, sp.test_end, series.tz),
        },
    }
    hist = SortedHistory(series.history)
    all_origins = {o for o, _ in first} | {o for o, _ in trace["fit_final"]} | {x[1] for x in trace["test"]} | \
                  {x[1] for v in trace["validation"].values() for x in v}
    audit["features_window_ends_le_origin_for_all_traced_origins"] = all(
        (not hist.window(o)[0]) or hist.window(o)[0][-1] + HOUR <= o for o in all_origins)
    audit["test_scored_targets_all_observed"] = all(t in series.history for x in trace["test"] for t in x[4])
    audit["checked_origins"] = len(all_origins)

    invariants = [audit["A_initial_fit"]["invariant_all_target_ends_le_cutoff"], audit["C_final_refit"]["invariant_all_target_ends_le_cutoff"],
                  audit["features_window_ends_le_origin_for_all_traced_origins"], audit["test_scored_targets_all_observed"],
                  audit["A_identical_rows_for_every_config"], audit["B_identical_origins_and_targets_for_every_config"]]
    for phase in ("B_validation", "D_test"):
        for h in HORIZONS:
            invariants += [v for k, v in audit[phase][h].items() if k.startswith("invariant_")]
    audit["all_invariants_hold"] = all(invariants)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
