"""Hourly profile-median baseline (BASELINE_VERSION "hourly-profile-median-v1").

For each forecast hour t (on the origin's hourly grid) with local weekday
d, local hour h and day class c (working if d is in working_days_iso):

1. weekday_hour   — median of observed history hours with the same (d, h),
                    if at least MIN_SUPPORT["weekday_hour"] observations;
2. day_class_hour — else the median over the same (c, h), if enough;
3. hour_of_day    — else the median over the same h on any day (disclosed
                    fallback), if enough;
4. otherwise the hour cannot be forecast → INSUFFICIENT_DATA.

The median is used because it is robust to single anomalous hours (faults,
one-off events) in a small history. Only observed hours contribute: missing
hours are absent, never zero. The same calendar classifies history and
horizon days (historical calendar changes and holidays are not modelled).
Deterministic: same input → same output. No weather, occupancy or schedule
inputs are used.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from ..errors import ApiError
from .constants import MIN_OBSERVED_HOURS, MIN_SUPPORT

HOUR = timedelta(hours=1)
LEVELS = ("weekday_hour", "day_class_hour", "hour_of_day")
ISO_DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


@dataclass(frozen=True)
class Horizon:
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive
    hours: list[datetime]  # UTC starts of each forecast hour


def horizon_bounds(horizon: str, origin: datetime, tz: ZoneInfo) -> Horizon:
    """Contract §8: next_24h/next_7d start at the origin; next_calendar_month is
    the complete local calendar month after the month containing the origin."""
    if horizon == "next_24h":
        start, end = origin, origin + timedelta(hours=24)
    elif horizon == "next_7d":
        start, end = origin, origin + timedelta(days=7)
    else:
        local = origin.astimezone(tz)
        y, m = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
        start = datetime(y, m, 1, tzinfo=tz).astimezone(timezone.utc)
        end = datetime(y2, m2, 1, tzinfo=tz).astimezone(timezone.utc)
        if (start - origin).total_seconds() % 3600 != 0:
            raise ApiError(400, "VALIDATION_ERROR",
                           "next_calendar_month needs an hourly grid aligned to local midnight: use an origin_utc on the local "
                           f"clock of {tz.key} (e.g. {start.strftime('%Y-%m-%dT%H:%M:%SZ')} is local 00:00)", "origin_utc")
    hours = []
    t = start
    while t < end:  # absolute hours; Asia/Kolkata has no DST
        hours.append(t)
        t += HOUR
    return Horizon(start, end, hours)


def slot(t: datetime, tz: ZoneInfo, working_days: set[int]) -> tuple[int, int, str]:
    local = t.astimezone(tz)
    day = local.isoweekday()
    return day, local.hour, "working" if day in working_days else "non_working"


@dataclass
class PointForecast:
    start: datetime
    energy_kwh: float
    basis: str
    support: int


def forecast(history: dict[datetime, float], hz: Horizon, tz: ZoneInfo, working_days: set[int], horizon: str) -> list[PointForecast]:
    observed = len(history)
    need = MIN_OBSERVED_HOURS[horizon]
    if observed < need:
        raise ApiError(422, "INSUFFICIENT_DATA",
                       f"{horizon} requires at least {need} observed history hours ({need // 24} days); got {observed}. "
                       "Missing hours are not treated as zero.", "history_hourly_kwh")

    buckets: dict[str, dict[tuple, list[float]]] = {level: {} for level in LEVELS}
    for t, kwh in history.items():
        day, hour, cls = slot(t, tz, working_days)
        buckets["weekday_hour"].setdefault((day, hour), []).append(kwh)
        buckets["day_class_hour"].setdefault((cls, hour), []).append(kwh)
        buckets["hour_of_day"].setdefault((hour,), []).append(kwh)

    points: list[PointForecast] = []
    unsupported: list[str] = []
    for t in hz.hours:
        day, hour, cls = slot(t, tz, working_days)
        keys = {"weekday_hour": (day, hour), "day_class_hour": (cls, hour), "hour_of_day": (hour,)}
        for level in LEVELS:
            values = buckets[level].get(keys[level], [])
            if len(values) >= MIN_SUPPORT[level]:
                points.append(PointForecast(t, median(values), level, len(values)))
                break
        else:
            label = f"{ISO_DAY_NAMES[day]} {hour:02d}:00 local"
            if label not in unsupported:
                unsupported.append(label)
    if unsupported:
        shown = ", ".join(unsupported[:6]) + (f" and {len(unsupported) - 6} more" if len(unsupported) > 6 else "")
        raise ApiError(422, "INSUFFICIENT_DATA",
                       f"No sufficiently supported history for {len(unsupported)} local weekday/hour slot(s) in the {horizon} horizon: "
                       f"{shown}. Each hour needs >= {MIN_SUPPORT['weekday_hour']} same-weekday observations, >= "
                       f"{MIN_SUPPORT['day_class_hour']} same day-class observations, or >= {MIN_SUPPORT['hour_of_day']} same-hour observations.",
                       "history_hourly_kwh")
    return points
