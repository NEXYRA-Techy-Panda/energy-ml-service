"""Offline training input format "nexyra-hourly-training-v1" (separate from the
telemetry contract; the shared contract is not changed).

A JSON file holding ONE hourly energy series:

    {
      "format": "nexyra-hourly-training-v1",
      "series_id": "office-main",
      "timezone": "Asia/Kolkata",
      "calendar": {"working_days_iso": [1, 2, 3, 4, 5]},
      "provenance": {"synthetic": true, "source": "...", "description": "...", ...},
      "points": [{"start_utc": "2026-01-01T18:30:00Z", "energy_kwh": 0.45}, ...]
    }

Rules: each point is one COMPLETE hour [start, start + 1 h); all points share
one hourly grid (a full hour in UTC or on the local clock); finite,
non-negative energy; identical duplicates are deduplicated (reported),
conflicting duplicates and invalid timestamps are rejected; missing hours
stay missing (never zero); injected-fault fields are rejected anywhere.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, StringConstraints, ValidationError, field_validator

from ..analysis.models import Closed, IsoDay, Utc
from ..analysis.validate import _find_forbidden, _loc
from ..forecast.constants import SUPPORTED_TIMEZONES

FORMAT = "nexyra-hourly-training-v1"
HOUR = timedelta(hours=1)


class TrainingInputError(ValueError):
    def __init__(self, message: str, path: str | None = None):
        super().__init__(f"{path}: {message}" if path else message)
        self.path = path


class Point(Closed):
    start_utc: Utc
    energy_kwh: Annotated[float, Field(ge=0, le=1_000_000)]

    @field_validator("energy_kwh")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("energy_kwh must be finite")
        return v


class TrainingCalendar(Closed):
    working_days_iso: Annotated[list[IsoDay], Field(min_length=1, max_length=7)]

    @field_validator("working_days_iso")
    @classmethod
    def _unique(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("ISO weekdays must be unique")
        return v


class Provenance(Closed):
    synthetic: bool
    source: Annotated[str, StringConstraints(min_length=1)]
    description: Annotated[str, StringConstraints(min_length=1)]
    scenario: str | None = None
    seed: int | None = None
    dataset_id: str | None = None
    run_id: str | None = None
    exported_utc: Utc | None = None
    generated_utc: Utc | None = None


class TrainingInputModel(Closed):
    format: Literal["nexyra-hourly-training-v1"]
    series_id: Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]
    timezone: Annotated[str, StringConstraints(min_length=1)]
    calendar: TrainingCalendar
    provenance: Provenance
    points: Annotated[list[Point], Field(min_length=1)]


@dataclass
class TrainingSeries:
    series_id: str
    tz: ZoneInfo
    working_days: set[int]
    provenance: dict[str, Any]
    history: dict[datetime, float]  # complete observed hours keyed by UTC start
    duplicates_deduped: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def start(self) -> datetime:
        return min(self.history)

    @property
    def end(self) -> datetime:
        return max(self.history) + HOUR


def parse_utc(value: str, path: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise TrainingInputError(f"{value!r} is not a real UTC timestamp", path) from None


def fmt_utc(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_training_input(data: Any) -> TrainingSeries:
    if not isinstance(data, dict):
        raise TrainingInputError("training input must be a JSON object")
    forbidden = _find_forbidden(data, "")
    if forbidden:
        raise TrainingInputError("injected-fault fields are forbidden in training input", forbidden)
    try:
        model = TrainingInputModel.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise TrainingInputError(first["msg"], _loc(first["loc"]) or None) from None
    if model.timezone not in SUPPORTED_TIMEZONES:
        raise TrainingInputError(f"timezone {model.timezone!r} is not supported ({', '.join(SUPPORTED_TIMEZONES)})", "timezone")
    tz = ZoneInfo(model.timezone)

    history: dict[datetime, float] = {}
    dupes = 0
    anchor: datetime | None = None
    for i, p in enumerate(model.points):
        where = f"points[{i}].start_utc"
        t = parse_utc(p.start_utc, where)
        if not (t.minute == 0 or t.astimezone(tz).minute == 0):
            raise TrainingInputError("each point must start on a full hour in UTC or on the local clock", where)
        if anchor is None:
            anchor = t
        elif (t - anchor).total_seconds() % 3600 != 0:
            raise TrainingInputError("mixed hourly grids in one series (incompatible series combined?)", where)
        if t in history:
            if history[t] != p.energy_kwh:
                raise TrainingInputError(f"conflicting duplicate observation for {p.start_utc}", f"points[{i}].energy_kwh")
            dupes += 1
            continue
        history[t] = p.energy_kwh
    return TrainingSeries(model.series_id, tz, set(model.calendar.working_days_iso), model.provenance.model_dump(exclude_none=True),
                          dict(sorted(history.items())), dupes)


def load_training_input(path: str | Path) -> TrainingSeries:
    def reject(name: str) -> float:
        raise TrainingInputError(f"non-finite number {name} is not allowed")

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise TrainingInputError(f"invalid JSON ({exc})") from None
    return parse_training_input(data)


def to_document(series: TrainingSeries) -> dict:
    return {
        "format": FORMAT,
        "series_id": series.series_id,
        "timezone": series.tz.key,
        "calendar": {"working_days_iso": sorted(series.working_days)},
        "provenance": series.provenance,
        "points": [{"start_utc": fmt_utc(t), "energy_kwh": v} for t, v in sorted(series.history.items())],
    }


def summarize(series: TrainingSeries) -> dict:
    span = int((series.end - series.start).total_seconds() // 3600)
    return {
        "series_id": series.series_id,
        "timezone": series.tz.key,
        "working_days_iso": sorted(series.working_days),
        "provenance": series.provenance,
        "start_utc": fmt_utc(series.start),
        "end_utc": fmt_utc(series.end),
        "span_hours": span,
        "observed_hours": len(series.history),
        "missing_hours": span - len(series.history),
        "duplicates_deduped": series.duplicates_deduped,
    }
