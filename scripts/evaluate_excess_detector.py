"""Held-out SYNTHETIC detection diagnostic for POST /v1/anomalies (P022).

Run: .venv\\Scripts\\python.exe scripts\\evaluate_excess_detector.py

- Cases: app.anomalies.synthetic.labelled_case(seed) for held-out seeds
  7001–7005 (fixed in advance; seed 1 was used only for a development smoke
  check). Detector parameters (app/anomalies/constants.py) were frozen before
  this ran and are not tuned on these labels.
- Labels are kept separate from the request (never service inputs).
- Unit: one (device, 5-minute evaluation interval). TP = labelled & flagged;
  FP = flagged & not labelled; FN = labelled & not flagged, split into
  "evaluated" (detector saw it and did not flag) and "not evaluated"
  (reading missing, excluded, or insufficient reference).
- Precision/recall are reported as undefined when their denominator is 0.
- SYNTHETIC diagnostics only — not real-building accuracy.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.anomalies.constants import DETECTOR_VERSION  # noqa: E402
from app.anomalies.service import run_anomalies  # noqa: E402
from app.anomalies.synthetic import labelled_case  # noqa: E402

SEEDS = (7001, 7002, 7003, 7004, 7005)


def ratio(num: int, den: int):
    return round(num / den, 4) if den else "undefined (denominator 0)"


def main() -> None:
    rows, tot = [], {"tp": 0, "fp": 0, "fn_evaluated": 0, "fn_not_evaluated": 0, "labels": 0, "strong": [0, 0], "subtle": [0, 0],
                     "evaluated": 0, "excluded": 0, "insufficient": 0, "evaluation_intervals": 0}
    for seed in SEEDS:
        body, labels = labelled_case(seed)
        r = run_anomalies(json.dumps(body).encode())
        flagged = {(f["device_id"], iv["interval_start_utc"]) for f in r["findings"] for iv in f["evidence"]["intervals"]}
        present = {(d["device_id"], d["interval_start_utc"]) for d in body["evaluation"]["device_intervals"]}
        excluded = {(e["device_id"], e["interval_start_utc"]) for e in r["exclusions"] if e["section"] == "evaluation"}
        tp = flagged & set(labels)
        fn = set(labels) - flagged
        fn_not_eval = {k for k in fn if k not in present or k in excluded}
        cov = r["coverage"]
        row = {"seed": seed, "status": r["status"], "labels": len(labels), "tp": len(tp), "fp": len(flagged - set(labels)),
               "fn_evaluated": len(fn - fn_not_eval), "fn_not_evaluated": len(fn_not_eval),
               "strong_detected": f"{sum(1 for k in tp if labels[k] == 'strong')}/{sum(1 for v in labels.values() if v == 'strong')}",
               "subtle_detected": f"{sum(1 for k in tp if labels[k] == 'subtle')}/{sum(1 for v in labels.values() if v == 'subtle')}",
               "evaluation_intervals": cov["evaluation_device_intervals"], "evaluated": cov["evaluated"],
               "excluded": sum(cov["excluded"].values()), "insufficient_reference": cov["insufficient_reference"],
               "findings": len(r["findings"])}
        rows.append(row)
        for k in ("tp", "fp", "fn_evaluated", "fn_not_evaluated", "labels", "evaluated", "excluded"):
            tot[k] += row[k]
        tot["insufficient"] += row["insufficient_reference"]
        tot["evaluation_intervals"] += row["evaluation_intervals"]
        for kind in ("strong", "subtle"):
            tot[kind][0] += sum(1 for k in tp if labels[k] == kind)
            tot[kind][1] += sum(1 for v in labels.values() if v == kind)
    fn = tot["fn_evaluated"] + tot["fn_not_evaluated"]
    report = {
        "data": "SYNTHETIC (app.anomalies.synthetic.labelled_case); not real-building accuracy",
        "detector_version": DETECTOR_VERSION, "seeds": list(SEEDS), "per_seed": rows,
        "totals": {**{k: v for k, v in tot.items() if k not in ("strong", "subtle")},
                   "strong_recall": ratio(*tot["strong"]), "subtle_recall": ratio(*tot["subtle"]),
                   "precision": ratio(tot["tp"], tot["tp"] + tot["fp"]), "recall": ratio(tot["tp"], tot["tp"] + fn),
                   "recall_among_evaluated_labels": ratio(tot["tp"], tot["tp"] + tot["fn_evaluated"])},
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
