"""Origin-anchored features (FEATURE_VERSION "origin-anchored-v1").

Multi-step strategy: DIRECT, not recursive. For a forecast origin o and any
target hour t = o + k h (k = 0 … horizon − 1), every feature is computed
from (a) the local calendar of t and (b) history observations that END at or
before o (the latest ≤ 2,160, as in a production request). No prediction is
fed back, and no observation at or after o — i.e. no horizon actual — can
enter any feature, for every horizon (24 h, 7 d, next calendar month).

Missing-data strategy: missing history hours are simply absent; aggregate
features are computed from observed hours only, and a feature with no
support is NaN (never 0). HistGradientBoostingRegressor handles NaN natively
(learned missing-value branches), so no imputer is fitted.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import nan
from statistics import mean, median
from zoneinfo import ZoneInfo

FEATURE_VERSION = "origin-anchored-v1"
FEATURE_NAMES = [
    "local_hour",  # 0–23 local hour of t
    "local_iso_weekday",  # 1–7
    "is_working_day",  # 1/0 from the documented calendar
    "lead_days",  # floor((t − o) / 24 h)
    "profile_weekday_hour",  # median of history at the same local weekday+hour (NaN if none)
    "profile_dayclass_hour",  # median at the same working/non-working class + hour (NaN if none)
    "last_obs_same_hour",  # most recent observed value at the same local hour before o (NaN if none)
    "mean_last_7d",  # mean of observed hours in [o − 7 d, o) (NaN if < 24 observed)
    "mean_last_28d",  # mean of observed hours in [o − 28 d, o) (NaN if < 96 observed)
    "support_weekday_hour",  # number of observations behind profile_weekday_hour
]
HISTORY_WINDOW_HOURS = 2160
HOUR = timedelta(hours=1)


class SortedHistory:
    """Observed hours sorted by start, for fast "ends at or before origin" windows."""

    def __init__(self, history: dict[datetime, float]):
        self.times = sorted(history)
        self.values = [history[t] for t in self.times]

    def window(self, origin: datetime, max_points: int = HISTORY_WINDOW_HOURS) -> tuple[list[datetime], list[float]]:
        # Observations ending at or before origin: start <= origin − 1 h.
        end = bisect_right(self.times, origin - HOUR)
        start = max(0, end - max_points)
        return self.times[start:end], self.values[start:end]


@dataclass
class OriginContext:
    origin: datetime
    observed: int
    by_weekday_hour: dict[tuple[int, int], tuple[float, int]]
    by_class_hour: dict[tuple[bool, int], float]
    last_by_hour: dict[int, float]
    mean_7d: float
    mean_28d: float


def origin_context(hist: SortedHistory, origin: datetime, tz: ZoneInfo, working_days: set[int]) -> OriginContext:
    times, values = hist.window(origin)
    wh: dict[tuple[int, int], list[float]] = {}
    ch: dict[tuple[bool, int], list[float]] = {}
    last: dict[int, float] = {}
    recent7: list[float] = []
    recent28: list[float] = []
    cut7, cut28 = origin - timedelta(days=7), origin - timedelta(days=28)
    for t, v in zip(times, values):  # ascending → later values overwrite "last"
        local = t.astimezone(tz)
        day, hour = local.isoweekday(), local.hour
        wh.setdefault((day, hour), []).append(v)
        ch.setdefault((day in working_days, hour), []).append(v)
        last[hour] = v
        if t >= cut28:
            recent28.append(v)
            if t >= cut7:
                recent7.append(v)
    return OriginContext(
        origin=origin,
        observed=len(values),
        by_weekday_hour={k: (median(v), len(v)) for k, v in wh.items()},
        by_class_hour={k: median(v) for k, v in ch.items()},
        last_by_hour=last,
        mean_7d=mean(recent7) if len(recent7) >= 24 else nan,
        mean_28d=mean(recent28) if len(recent28) >= 96 else nan,
    )


def features_for(ctx: OriginContext, t: datetime, tz: ZoneInfo, working_days: set[int]) -> list[float]:
    local = t.astimezone(tz)
    day, hour = local.isoweekday(), local.hour
    working = day in working_days
    wh = ctx.by_weekday_hour.get((day, hour))
    return [
        float(hour),
        float(day),
        1.0 if working else 0.0,
        float((t - ctx.origin) // timedelta(days=1)),
        wh[0] if wh else nan,
        ctx.by_class_hour.get((working, hour), nan),
        ctx.last_by_hour.get(hour, nan),
        ctx.mean_7d,
        ctx.mean_28d,
        float(wh[1]) if wh else 0.0,
    ]
