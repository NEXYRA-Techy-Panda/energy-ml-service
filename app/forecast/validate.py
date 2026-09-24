"""Parsing and semantic validation for POST /v1/forecast.

Order: body size → JSON (NaN/Infinity rejected) → contract_version →
history bound (413) → forbidden fault fields → closed models → semantics.

Time semantics (local API clarification, documented in the evidence):
- The forecast grid is hourly and anchored at origin_utc: every point is
  origin + k hours. origin_utc must be a full hour either in UTC (HH:00Z)
  or on the calendar timezone's local clock (Asia/Kolkata: HH:30Z).
- Every history point is one complete hour [start_utc, start_utc + 1 h) on
  the same grid, ending at or before the origin. Later points are future
  observations and are rejected. Partial hours are not accepted or resampled.
- Missing hours are gaps, never zeros.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..analysis.validate import _find_forbidden, _loc
from ..config import CONTRACT_VERSION
from ..errors import ApiError
from .constants import BASELINE_VERSION, MAX_BODY_BYTES, MAX_HISTORY_POINTS, SUPPORTED_TIMEZONES
from .models import ForecastRequest

HOUR = timedelta(hours=1)


def parse_utc(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", f"{value!r} is not a real UTC timestamp", field_name) from None


def fmt_utc(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ParsedForecast:
    request: ForecastRequest
    tz: ZoneInfo
    origin: datetime
    history: dict[datetime, float]  # observed complete hours, keyed by start (UTC)
    duplicates_deduped: int = 0
    notes: list[str] = field(default_factory=list)


def _reject_constant(name: str) -> float:
    raise ValueError(f"non-finite number {name} is not allowed")


def parse_forecast(raw: bytes) -> ParsedForecast:
    if len(raw) > MAX_BODY_BYTES:
        raise ApiError(413, "REQUEST_TOO_LARGE", f"Request body exceeds {MAX_BODY_BYTES} bytes")
    try:
        data = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiError(400, "VALIDATION_ERROR", f"Request body is not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Request body must be a JSON object")

    version = data.get("contract_version")
    if version is None:
        raise ApiError(400, "VALIDATION_ERROR", "contract_version is required", "contract_version")
    if version != CONTRACT_VERSION:
        raise ApiError(400, "UNSUPPORTED_VERSION", f"contract_version {version!r} is not supported (expected {CONTRACT_VERSION})", "contract_version")

    history = data.get("history_hourly_kwh")
    if isinstance(history, list) and len(history) > MAX_HISTORY_POINTS:
        raise ApiError(413, "REQUEST_TOO_LARGE",
                       f"history_hourly_kwh has {len(history)} points; the bound is {MAX_HISTORY_POINTS} (90 days)", "history_hourly_kwh")

    forbidden = _find_forbidden(data, "")
    if forbidden:
        raise ApiError(400, "VALIDATION_ERROR", f"Injected-fault field {forbidden.rsplit('.', 1)[-1]!r} is forbidden in forecast inputs", forbidden)

    try:
        req = ForecastRequest.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(400, "VALIDATION_ERROR", first["msg"], _loc(first["loc"]) or None) from None

    return _semantics(req)


def _semantics(req: ForecastRequest) -> ParsedForecast:
    cal = req.calendar
    if cal.timezone not in SUPPORTED_TIMEZONES:
        raise ApiError(400, "VALIDATION_ERROR",
                       f"calendar.timezone {cal.timezone!r} is not supported; contract v1 buildings use {', '.join(SUPPORTED_TIMEZONES)}",
                       "calendar.timezone")
    if cal.open_local == cal.close_local:
        raise ApiError(400, "VALIDATION_ERROR", "calendar.open_local and close_local must differ", "calendar.close_local")
    derived_overnight = cal.close_local < cal.open_local
    if cal.overnight is not None and cal.overnight != derived_overnight:
        raise ApiError(400, "VALIDATION_ERROR", f"calendar.overnight must be {derived_overnight} for {cal.open_local}–{cal.close_local}", "calendar.overnight")
    if req.model is not None and req.model.version != BASELINE_VERSION:
        raise ApiError(400, "VALIDATION_ERROR",
                       f"model.version {req.model.version!r} is not available; no trained model exists. Omit model or use the baseline "
                       f"{BASELINE_VERSION!r}", "model.version")

    tz = ZoneInfo(cal.timezone)
    origin = parse_utc(req.origin_utc, "origin_utc")
    if origin.second != 0 or not (origin.minute == 0 or origin.astimezone(tz).minute == 0):
        local_hour_minute = (60 - int(origin.astimezone(tz).utcoffset().total_seconds() // 60) % 60) % 60
        raise ApiError(400, "VALIDATION_ERROR",
                       "origin_utc must be a full hour in UTC (HH:00:00Z) or on the local clock of "
                       f"{cal.timezone} (HH:{local_hour_minute:02d}:00Z)", "origin_utc")

    history: dict[datetime, float] = {}
    dupes = 0
    previous: datetime | None = None
    for i, point in enumerate(req.history_hourly_kwh):
        where = f"history_hourly_kwh[{i}]"
        start = parse_utc(point.start_utc, f"{where}.start_utc")
        if (origin - start).total_seconds() % 3600 != 0:
            raise ApiError(400, "VALIDATION_ERROR",
                           "History points must be complete hours on the same hourly grid as origin_utc", f"{where}.start_utc", row=i)
        if start + HOUR > origin:
            raise ApiError(400, "VALIDATION_ERROR",
                           f"Observation {point.start_utc} ends after the forecast origin {req.origin_utc} (future observations are not allowed)",
                           f"{where}.start_utc", row=i)
        if previous is not None and start < previous:
            raise ApiError(400, "VALIDATION_ERROR", "history_hourly_kwh must be in ascending start_utc order", f"{where}.start_utc", row=i)
        previous = start
        if start in history:
            if history[start] != point.energy_kwh:
                raise ApiError(400, "VALIDATION_ERROR",
                               f"Conflicting duplicate observation for {point.start_utc}", f"{where}.energy_kwh", row=i)
            dupes += 1
            continue
        history[start] = point.energy_kwh
    return ParsedForecast(req, tz, origin, history, dupes)
