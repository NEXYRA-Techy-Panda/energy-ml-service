"""Offline chronological holdout evaluation of the forecast baseline on SYNTHETIC data.

Run: .venv\\Scripts\\python.exe scripts\\evaluate_forecast_baseline.py   (Linux: .venv/bin/python ...)

- Data: app.forecast.synthetic (invented office load, NOT measured). Reporting
  seed 20260924 is used only here (tests use other seeds). Baseline
  parameters (app/forecast/constants.py) were fixed before this ran and are
  not tuned on these results.
- For each cutoff only earlier observations (latest <= 2,160) are visible;
  the following horizon's observed hours are the withheld truth.
- Compared: profile-median baseline vs repeat-last-day, on identical hours.
- Metrics: MAE (kWh/hour) and aggregate energy error per origin (kWh). No
  percentages. Results describe synthetic data only, not real-building accuracy.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.forecast.constants import BASELINE_VERSION  # noqa: E402
from app.forecast.evaluation import holdout  # noqa: E402
from app.forecast.synthetic import SYNTHETIC_LABEL, synthetic_history  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
SEED = 20260924
WORKING = {1, 2, 3, 4, 5}


def local(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=IST).astimezone(timezone.utc)


def main() -> None:
    history = synthetic_history(datetime(2026, 10, 5, tzinfo=IST), 150, seed=SEED, missing_rate=0.05, noise=0.08)
    plans = {
        "next_24h": [local(2027, 1, 4) + timedelta(days=i) for i in range(28)],
        "next_7d": [local(2027, 1, 4) + timedelta(weeks=i) for i in range(4)],
        "next_calendar_month": [local(2026, 12, 15), local(2027, 1, 15)],
    }
    report = {"data": SYNTHETIC_LABEL, "seed": SEED, "baseline_version": BASELINE_VERSION,
              "history_hours_generated": len(history), "horizons": {}}
    for horizon, cutoffs in plans.items():
        totals = {"baseline": [0, 0.0, []], "repeat_last_day": [0, 0.0, []]}
        for cutoff in cutoffs:
            for method, score in holdout(history, cutoff, horizon, IST, WORKING).items():
                acc = totals[method]
                acc[0] += score.hours_scored
                acc[1] += score.mae_kwh_per_hour * score.hours_scored
                acc[2].append(score.aggregate_error_kwh)
        report["horizons"][horizon] = {
            "origins": len(cutoffs),
            **{method: {
                "hours_scored": hours,
                "mae_kwh_per_hour": round(abs_sum / hours, 4),
                "mean_abs_aggregate_error_kwh_per_origin": round(sum(abs(e) for e in errs) / len(errs), 3),
                "mean_aggregate_error_kwh_per_origin": round(sum(errs) / len(errs), 3),
            } for method, (hours, abs_sum, errs) in totals.items()},
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
