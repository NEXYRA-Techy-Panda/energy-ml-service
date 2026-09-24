"""Offline training CLI (P016). Windows PowerShell, from the repo root:

  .venv\\Scripts\\python.exe -m app.training.cli generate --scenario trend_regime --seed 101 --out data\\training\\trend_regime-101.json
  .venv\\Scripts\\python.exe -m app.training.cli validate --input data\\training\\trend_regime-101.json
  .venv\\Scripts\\python.exe -m app.training.cli train --input data\\training\\trend_regime-101.json --cutoff-days 350 --config hgb-mae-small --seed 0 --out artifacts\\candidates\\demo
  .venv\\Scripts\\python.exe -m app.training.cli evaluate --input data\\training\\trend_regime-101.json --seed 0 --report artifacts\\reports\\trend_regime-101.json --save-bundle artifacts\\candidates\\trend_regime-101
  .venv\\Scripts\\python.exe -m app.training.cli predict --bundle artifacts\\candidates\\trend_regime-101 --input data\\training\\trend_regime-101.json --origin 2026-10-19T18:30:00Z --horizon next_7d --check-reload
  .venv\\Scripts\\python.exe -m app.training.cli suite --report artifacts\\reports\\p016-suite.json

data/ and artifacts/ are git-ignored: datasets and model binaries are generated
locally and never committed.
"""

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

from .candidate import CONFIGS, load_bundle, predict_horizon, save_bundle, train
from .evaluate import HORIZONS, METHODS, run_experiment, splits_for
from .input import TrainingInputError, fmt_utc, load_training_input, parse_utc, summarize, to_document
from .synthetic import SCENARIOS, generate

SUITE_SEEDS = (101, 202, 303)  # fixed in advance; every seed is reported (no cherry-picking)


def _write_json(path: str, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def cmd_generate(a) -> None:
    series = generate(a.scenario, a.seed, a.days)
    _write_json(a.out, to_document(series))
    print(json.dumps(summarize(series), indent=2))


def cmd_validate(a) -> None:
    print(json.dumps({"valid": True, **summarize(load_training_input(a.input))}, indent=2))


def cmd_train(a) -> None:
    series = load_training_input(a.input)
    cutoff = parse_utc(a.cutoff, "--cutoff") if a.cutoff else splits_for(series).start + timedelta(days=a.cutoff_days)
    cand = train(series, cutoff, a.config, a.seed)
    out = save_bundle(cand, a.out)
    print(json.dumps({"bundle": str(out), "training_cutoff_utc": fmt_utc(cutoff), "training_rows": cand.training_rows,
                      "fit_seconds": round(cand.fit_seconds, 2)}, indent=2))


def cmd_evaluate(a) -> None:
    series = load_training_input(a.input)
    report, final = run_experiment(series, a.seed)
    if a.report:
        _write_json(a.report, report)
    if a.save_bundle:
        save_bundle(final, a.save_bundle, evaluation={"selection": report["selection"], "splits": report["splits"], "test": report["test"]})
    print(json.dumps(_summary_rows([report]), indent=2))


def cmd_predict(a) -> None:
    cand = load_bundle(a.bundle)
    series = load_training_input(a.input)
    origin = parse_utc(a.origin, "--origin")
    if origin < cand.training_cutoff:
        print(f"note: origin is before the bundle's training cutoff {fmt_utc(cand.training_cutoff)} (in-sample period)", file=sys.stderr)
    pred = predict_horizon(cand, series.history, origin, a.horizon)
    result = {"model_id": cand.metadata.get("model_id"), "status": cand.metadata.get("status"), "horizon": a.horizon,
              "origin_utc": a.origin, "points": [{"start_utc": fmt_utc(t), "energy_kwh": v} for t, v in pred.items()],
              "total_energy_kwh": sum(pred.values())}
    if a.check_reload:
        again = predict_horizon(load_bundle(a.bundle), series.history, origin, a.horizon)
        result["reload_identical"] = again == pred
    print(json.dumps(result, indent=2))


def _summary_rows(reports: list[dict]) -> list[dict]:
    rows = []
    for r in reports:
        for h in HORIZONS:
            t = r["test"][h]
            rows.append({
                "series": r["series_id"], "seed_model": r["seed"], "horizon": h, "config": r["selection"]["selected_config"],
                "origins": t["origins"], "eligible": t["origins_eligible"], "failures": t["failures"],
                "hours_expected": t["hours_expected"], "hours_scored_common": t["hours_scored_common"],
                **{f"mae_{m}": (round(t["methods"][m]["mae_kwh_per_hour"], 4) if t["methods"][m]["mae_kwh_per_hour"] is not None else None)
                   for m in METHODS},
                **{f"energy_err_abs_{m}": (round(t["methods"][m]["energy_error_over_common_scored_hours_kwh"]["mean_abs_per_origin"], 2)
                                           if t["methods"][m]["energy_error_over_common_scored_hours_kwh"]["mean_abs_per_origin"] is not None else None)
                   for m in METHODS},
            })
    return rows


def cmd_suite(a) -> None:
    seeds = tuple(int(s) for s in a.seeds.split(",")) if a.seeds else SUITE_SEEDS
    reports = []
    t0 = time.perf_counter()
    for scenario in SCENARIOS:
        for seed in seeds:
            series = generate(scenario, seed)
            report, _ = run_experiment(series, seed=0)
            report["data_seed"] = seed
            reports.append(report)
            print(f"done {scenario} seed {seed} (selected {report['selection']['selected_config']})", file=sys.stderr)
    summary = _summary_rows(reports)
    suite = {"synthetic": True, "note": "SYNTHETIC data only; not real-building accuracy.", "scenarios": list(SCENARIOS),
             "data_seeds": list(seeds), "model_seed": 0, "configs": CONFIGS, "wall_seconds": round(time.perf_counter() - t0, 1),
             "summary": summary, "reports": reports}
    if a.report:
        _write_json(a.report, suite)
    print(json.dumps(summary, indent=2))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.training.cli", description="Offline forecast-candidate training (P016)")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="write a SYNTHETIC training input")
    g.add_argument("--scenario", choices=SCENARIOS, required=True)
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--days", type=int, default=430)
    g.add_argument("--out", required=True)
    v = sub.add_parser("validate", help="validate a training input file")
    v.add_argument("--input", required=True)
    t = sub.add_parser("train", help="train one config and save a local bundle")
    t.add_argument("--input", required=True)
    t.add_argument("--cutoff", help="UTC training cutoff (hours ending at or before it)")
    t.add_argument("--cutoff-days", type=int, default=350, help="cutoff as days after the first local midnight (default 350)")
    t.add_argument("--config", choices=list(CONFIGS), default="hgb-mae-small")
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--out", required=True)
    e = sub.add_parser("evaluate", help="temporal train/validation/test evaluation for one input")
    e.add_argument("--input", required=True)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--report")
    e.add_argument("--save-bundle")
    s = sub.add_parser("suite", help="all SYNTHETIC scenarios x fixed seeds")
    s.add_argument("--seeds")
    s.add_argument("--report")
    pr = sub.add_parser("predict", help="offline prediction from a locally produced bundle")
    pr.add_argument("--bundle", required=True)
    pr.add_argument("--input", required=True)
    pr.add_argument("--origin", required=True)
    pr.add_argument("--horizon", choices=HORIZONS, default="next_24h")
    pr.add_argument("--check-reload", action="store_true")
    args = p.parse_args(argv)
    try:
        {"generate": cmd_generate, "validate": cmd_validate, "train": cmd_train, "evaluate": cmd_evaluate,
         "suite": cmd_suite, "predict": cmd_predict}[args.cmd](args)
    except TrainingInputError as exc:
        print(f"invalid training input: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
