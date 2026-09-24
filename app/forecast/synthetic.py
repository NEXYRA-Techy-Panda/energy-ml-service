"""SYNTHETIC hourly office-load generator for tests and offline evaluation only.

Never used by the request path. Output is invented data with a known shape;
performance measured on it says nothing about any real building.

Shape (kWh per hour): always-on base 0.45; on working days 09:00–18:00
local an extra 5.0 (Mondays +0.4, 13:00 lunch hour −1.5), with multiplicative
Gaussian noise; optional random missing hours. Deterministic for a seed.
"""

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SYNTHETIC_LABEL = "SYNTHETIC generated office load (not measured data)"


def synthetic_history(start_local: datetime, days: int, *, seed: int, working_days: set[int] | None = None,
                      missing_rate: float = 0.0, noise: float = 0.08) -> dict[datetime, float]:
    """Hourly points keyed by UTC start, on the local-hour grid of start_local's timezone."""
    tz = start_local.tzinfo
    assert isinstance(tz, ZoneInfo)
    working = working_days if working_days is not None else {1, 2, 3, 4, 5}
    rng = random.Random(seed)
    out: dict[datetime, float] = {}
    t = start_local.astimezone(timezone.utc)
    for _ in range(days * 24):
        local = t.astimezone(tz)
        load = 0.45
        if local.isoweekday() in working and 9 <= local.hour < 18:
            load += 5.0 + (0.4 if local.isoweekday() == 1 else 0.0) - (1.5 if local.hour == 13 else 0.0)
        value = max(0.0, load * (1 + rng.gauss(0, noise)))
        if rng.random() >= missing_rate:
            out[t] = value
        t += timedelta(hours=1)
    return out
