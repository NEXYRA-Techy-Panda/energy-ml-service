"""Trained forecast candidate: scikit-learn HistGradientBoostingRegressor on
origin-anchored features (CPU only, seconds to train).

- Predetermined configuration set (CONFIGS); no search beyond it.
- early_stopping=False: HGB's automatic early stopping would carve a RANDOM
  (non-temporal) validation split out of the training rows; temporal
  selection happens outside, on a later validation period.
- Negative predictions are clipped to 0 kWh (energy cannot be negative); the
  same clip is applied in evaluation and in bundle inference.
- A candidate is eligible to forecast an origin only if >= MIN_WINDOW_OBS
  observed hours end at or before it (same as the baseline's 24 h minimum).
- Bundles are produced locally by this workflow (joblib). Loading a joblib
  file executes Python pickle code, so only load bundles you generated
  yourself; the recorded SHA-256 guards against accidental corruption, not
  against a malicious file.
"""

import hashlib
import json
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from ..forecast.baseline import horizon_bounds
from .features import FEATURE_NAMES, FEATURE_VERSION, OriginContext, SortedHistory, features_for, origin_context
from .input import TrainingSeries, fmt_utc

MODEL_FAMILY = "hgb-origin-anchored"
BUNDLE_FORMAT = "nexyra-forecast-candidate-bundle-v1"
MIN_WINDOW_OBS = 168
MAX_LEAD_HOURS = 62 * 24  # covers every next_calendar_month horizon from any origin
TRAIN_ORIGIN_START_DAYS = 14  # first training origin: two weeks after the series start

CONFIGS: dict[str, dict[str, Any]] = {
    "hgb-mae-small": {"loss": "absolute_error", "learning_rate": 0.05, "max_iter": 200, "max_leaf_nodes": 15, "min_samples_leaf": 20},
    "hgb-mse-small": {"loss": "squared_error", "learning_rate": 0.05, "max_iter": 200, "max_leaf_nodes": 15, "min_samples_leaf": 20},
    "hgb-mae-medium": {"loss": "absolute_error", "learning_rate": 0.05, "max_iter": 400, "max_leaf_nodes": 31, "min_samples_leaf": 40},
}


class CandidateUnavailable(Exception):
    """The candidate cannot forecast this origin (insufficient visible history)."""


@dataclass
class Candidate:
    model: HistGradientBoostingRegressor
    config_name: str
    params: dict[str, Any]
    seed: int
    training_cutoff: datetime
    tz_key: str
    working_days: set[int]
    series_id: str
    provenance: dict[str, Any]
    training_rows: int
    fit_seconds: float
    feature_build_seconds: float
    metadata: dict[str, Any] = field(default_factory=dict)


def local_midnights(start: datetime, end: datetime, tz) -> list[datetime]:
    """UTC instants of local midnights in [start, end)."""
    local = start.astimezone(tz)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if day < local:
        day += timedelta(days=1)
    out = []
    while day.astimezone(timezone.utc) < end:
        out.append(day.astimezone(timezone.utc))
        day = (day + timedelta(days=1)).replace(hour=0)
    return out


def build_training_rows(series: TrainingSeries, cutoff: datetime) -> tuple[np.ndarray, np.ndarray]:
    """Rows (origin, lead) with origins at local midnights; every target hour ends
    at or before `cutoff`, and each row's features see only hours before its origin."""
    hist = SortedHistory(series.history)
    xs: list[list[float]] = []
    ys: list[float] = []
    for origin in local_midnights(series.start + timedelta(days=TRAIN_ORIGIN_START_DAYS), cutoff, series.tz):
        ctx = origin_context(hist, origin, series.tz, series.working_days)
        if ctx.observed < MIN_WINDOW_OBS:
            continue
        for k in range(MAX_LEAD_HOURS):
            t = origin + timedelta(hours=k)
            if t + timedelta(hours=1) > cutoff:
                break
            y = series.history.get(t)
            if y is None:
                continue  # missing target hour: not a training row (never 0)
            xs.append(features_for(ctx, t, series.tz, series.working_days))
            ys.append(y)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def train(series: TrainingSeries, cutoff: datetime, config_name: str, seed: int = 0,
          params_override: dict[str, Any] | None = None) -> Candidate:
    """Fit on hours that END at or before `cutoff` only."""
    params = {**CONFIGS[config_name], **(params_override or {})}
    t0 = time.perf_counter()
    X, y = build_training_rows(series, cutoff)
    t1 = time.perf_counter()
    if len(y) == 0:
        raise CandidateUnavailable("no training rows before the cutoff")
    model = HistGradientBoostingRegressor(**params, early_stopping=False, random_state=seed)
    model.fit(X, y)
    t2 = time.perf_counter()
    return Candidate(model, config_name, params, seed, cutoff, series.tz.key, set(series.working_days), series.series_id,
                     dict(series.provenance), len(y), t2 - t1, t1 - t0)


def predict_context(candidate: Candidate, ctx: OriginContext, hours: list[datetime], tz, working_days: set[int]) -> dict[datetime, float]:
    if ctx.observed < MIN_WINDOW_OBS:
        raise CandidateUnavailable(f"only {ctx.observed} observed hours before the origin (needs {MIN_WINDOW_OBS})")
    X = np.asarray([features_for(ctx, t, tz, working_days) for t in hours], dtype=float)
    pred = np.clip(candidate.model.predict(X), 0.0, None)  # documented clip, applied everywhere
    return dict(zip(hours, pred.tolist()))


def predict_horizon(candidate: Candidate, history: dict[datetime, float], origin: datetime, horizon: str) -> dict[datetime, float]:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(candidate.tz_key)
    hz = horizon_bounds(horizon, origin, tz)
    ctx = origin_context(SortedHistory(history), origin, tz, candidate.working_days)
    return predict_context(candidate, ctx, hz.hours, tz, candidate.working_days)


# ------------------------------------------------------------------ bundles


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dependency_versions() -> dict[str, str]:
    import joblib as jl

    return {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "numpy": np.__version__, "joblib": jl.__version__}


def save_bundle(candidate: Candidate, directory: str | Path, evaluation: dict | None = None) -> Path:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    model_path = out / "model.joblib"
    joblib.dump(candidate.model, model_path)
    metadata = {
        "bundle_format": BUNDLE_FORMAT,
        "model_id": f"{MODEL_FAMILY}-{candidate.config_name}-{candidate.series_id}-{fmt_utc(candidate.training_cutoff)}",
        "model_family": MODEL_FAMILY,
        "config_name": candidate.config_name,
        "params": candidate.params,
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "training_cutoff_utc": fmt_utc(candidate.training_cutoff),
        "timezone": candidate.tz_key,
        "working_days_iso": sorted(candidate.working_days),
        "seed": candidate.seed,
        "series_id": candidate.series_id,
        "provenance": candidate.provenance,
        "training_rows": candidate.training_rows,
        "fit_seconds": round(candidate.fit_seconds, 3),
        "feature_build_seconds": round(candidate.feature_build_seconds, 3),
        "clip_negative_to_zero": True,
        "min_window_obs": MIN_WINDOW_OBS,
        "max_lead_hours": MAX_LEAD_HOURS,
        "dependency_versions": dependency_versions(),
        "created_utc": fmt_utc(datetime.now(timezone.utc)),
        "model_sha256": _sha256(model_path),
        "status": "offline candidate — NOT deployed; not loaded by /v1/forecast; model_available stays false",
        "evaluation": evaluation,
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return out


def load_bundle(directory: str | Path) -> Candidate:
    """Load a bundle produced locally by save_bundle (checks format, feature version and hash)."""
    d = Path(directory)
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    if meta.get("bundle_format") != BUNDLE_FORMAT:
        raise ValueError(f"unsupported bundle format {meta.get('bundle_format')!r}")
    if meta.get("feature_version") != FEATURE_VERSION:
        raise ValueError(f"bundle feature version {meta.get('feature_version')!r} != code {FEATURE_VERSION!r}")
    model_path = d / "model.joblib"
    if _sha256(model_path) != meta.get("model_sha256"):
        raise ValueError("model.joblib does not match the recorded SHA-256; refusing to load")
    model = joblib.load(model_path)
    cutoff = datetime.strptime(meta["training_cutoff_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return Candidate(model, meta["config_name"], meta["params"], meta["seed"], cutoff, meta["timezone"], set(meta["working_days_iso"]),
                     meta["series_id"], meta["provenance"], meta["training_rows"], meta["fit_seconds"], meta["feature_build_seconds"], meta)
