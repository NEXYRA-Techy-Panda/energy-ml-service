"""Chronological holdout evaluation (offline; NOT used by the request path).

For a cutoff c, only observations with start + 1 h <= c are visible to the
forecasters; observed hours in [c, c + horizon) are the withheld truth.

Compared methods:
- baseline: the production profile-median baseline (same code path as
  POST /v1/forecast), fitted on the visible history only;
- repeat_last_day: each horizon hour takes the value observed exactly 24 h
  earlier, stepping back further by whole days until a visible observation
  is found (i.e. the last observed day, repeated).

Metrics are computed over COMMON SCORED HOURS only: withheld horizon hours
that have an observation AND a prediction from every compared method. They
are MAE (kWh per hour) and the energy error over those common scored hours
(sum predicted − sum actual, kWh). When hours are missing this is NOT the
complete-horizon total error; expected_hours (all horizon hours) is reported
alongside hours_scored. No percentage metrics (zero denominators are possible).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .baseline import forecast, horizon_bounds
from .constants import MAX_HISTORY_POINTS

HOUR = timedelta(hours=1)


@dataclass
class Score:
    method: str
    expected_hours: int  # all horizon hours for this origin
    hours_scored: int  # common scored hours (observed and predicted by every compared method)
    mae_kwh_per_hour: float
    energy_error_common_kwh: float  # sum predicted − sum actual over the common scored hours only


def visible_history(history: dict[datetime, float], cutoff: datetime) -> dict[datetime, float]:
    """Only observations that end at or before the cutoff (no future leakage),
    limited to the latest MAX_HISTORY_POINTS as a production request would be."""
    past = sorted(t for t in history if t + HOUR <= cutoff)[-MAX_HISTORY_POINTS:]
    return {t: history[t] for t in past}


def repeat_last_day(visible: dict[datetime, float], hours: list[datetime]) -> dict[datetime, float]:
    out = {}
    for t in hours:
        back = t - timedelta(days=1)
        while back >= min(visible) and back not in visible:
            back -= timedelta(days=1)
        if back in visible:
            out[t] = visible[back]
    return out


def _score(method: str, predicted: dict[datetime, float], actual: dict[datetime, float], expected_hours: int) -> Score:
    common = [t for t in actual if t in predicted]
    errors = [predicted[t] - actual[t] for t in common]
    return Score(method, expected_hours, len(common), sum(abs(e) for e in errors) / len(common) if common else float("nan"), sum(errors))


def holdout(history: dict[datetime, float], cutoff: datetime, horizon: str, tz: ZoneInfo, working_days: set[int]) -> dict[str, Score]:
    visible = visible_history(history, cutoff)
    hz = horizon_bounds(horizon, cutoff, tz)
    actual = {t: history[t] for t in hz.hours if t in history}
    baseline = {p.start: p.energy_kwh for p in forecast(visible, hz, tz, working_days, horizon)}
    naive = repeat_last_day(visible, hz.hours)
    # Score both on the same hours so the comparison is like-for-like.
    both = {t: v for t, v in actual.items() if t in baseline and t in naive}
    n = len(hz.hours)
    return {"baseline": _score("baseline", baseline, both, n), "repeat_last_day": _score("repeat_last_day", naive, both, n)}
