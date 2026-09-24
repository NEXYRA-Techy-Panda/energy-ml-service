"""Held-out SYNTHETIC diagnostic for POST /v1/drift (P024).

Run: .venv\\Scripts\\python.exe scripts\\evaluate_drift_detector.py

- Cases: app.drift.synthetic.labelled_case(seed) for held-out seeds 9001–9020
  (never used during development; tests use hand-built development cases and
  the development smoke seed 1). Each case: 4 devices, 14 reference + 28
  evaluation days of hourly data (local 09–17), 20 % of evaluation days
  missing, 3 % missing hours, ±1.5 % noise; each device gets one scenario:
  gradual (+20–35 % over the period), small (+2–5 %), stable, spike (one day
  ×1.5–2.0), step (+20–40 % at a random day), offset (+15–30 % from the start).
- Detector parameters (app/drift/constants.py) were frozen before this ran.
- Labels are kept outside the requests. Unit = one device series.
  TP = "gradual" flagged; FP = any other label flagged; FN = "gradual" not
  flagged. Precision/recall are "undefined" when their denominator is 0.
- SYNTHETIC diagnostics only — not real-building performance.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.drift.constants import DETECTOR_VERSION  # noqa: E402
from app.drift.service import run_drift  # noqa: E402
from app.drift.synthetic import labelled_case  # noqa: E402

SEEDS = tuple(range(9001, 9021))


def ratio(num: int, den: int):
    return round(num / den, 4) if den else "undefined (denominator 0)"


def main() -> None:
    confusion: dict[str, Counter] = defaultdict(Counter)
    statuses: Counter = Counter()
    excluded: Counter = Counter()
    tp = fp = fn_eval = fn_not = 0
    for seed in SEEDS:
        body, labels = labelled_case(seed)
        r = run_drift(json.dumps(body).encode())
        flagged = {f["device_id"] for f in r["findings"]}
        for d in r["devices"]:
            label = labels[d["device_id"]]
            statuses[d["status"]] += 1
            for section in ("reference", "evaluation"):
                for reason, n in d["excluded"][section].items():
                    excluded[f"{section}:{reason}"] += n
            outcome = d["classification"] or d["status"]
            confusion[label][outcome] += 1
            if d["device_id"] in flagged:
                if label == "gradual":
                    tp += 1
                else:
                    fp += 1
            elif label == "gradual":
                if d["status"] == "evaluated":
                    fn_eval += 1
                else:
                    fn_not += 1
    report = {
        "data": "SYNTHETIC (app.drift.synthetic.labelled_case); not real-building performance",
        "detector_version": DETECTOR_VERSION, "seeds": [SEEDS[0], SEEDS[-1]], "device_series": sum(statuses.values()),
        "device_status_counts": dict(statuses),
        "classification_by_label": {k: dict(v) for k, v in sorted(confusion.items())},
        "excluded_intervals": dict(excluded),
        "totals": {"tp": tp, "fp": fp, "fn_evaluated": fn_eval, "fn_not_evaluated": fn_not,
                   "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn_eval + fn_not)},
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
