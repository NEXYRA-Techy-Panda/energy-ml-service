"""SYNTHETIC training series for offline evaluation (P016). Invented data with
known structure; results on it say nothing about real-building accuracy.

Scenarios (all Asia/Kolkata, local-hour grid, documented calendar Mon–Fri):
- weekly_stable: base 0.45 kWh/h; working hours 09–18 +5.0 (Mon +0.4,
  13:00 −1.5); ±8 % noise; 3 % missing hours.
- trend_regime: weekly_stable shape with working load growing 0.1 %/day, and
  a REGIME CHANGE on day 330: always-on base +0.25 kWh/h and Saturdays
  become half working days (09–13, +3.0). The documented calendar is NOT
  updated (models must cope from data alone). ±8 % noise; 3 % missing.
- seasonal_ac: weekly_stable shape plus a seasonal cooling load during
  working hours, 2.5 × max(0, sin(2π(doy − 60)/365)) kWh/h (peaking mid-year);
  ±10 % noise; 5 % missing.
"""

import random
from datetime import datetime, timedelta, timezone
from math import pi, sin
from zoneinfo import ZoneInfo

from .input import TrainingSeries

SCENARIOS = ("weekly_stable", "trend_regime", "seasonal_ac")
DEFAULT_START_LOCAL = (2025, 10, 6)  # Monday
DEFAULT_DAYS = 430
REGIME_CHANGE_DAY = 330
IST = ZoneInfo("Asia/Kolkata")


def generate(scenario: str, seed: int, days: int = DEFAULT_DAYS, start_local: tuple[int, int, int] = DEFAULT_START_LOCAL) -> TrainingSeries:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {', '.join(SCENARIOS)}")
    rng = random.Random(f"{scenario}:{seed}")
    noise = 0.10 if scenario == "seasonal_ac" else 0.08
    missing = 0.05 if scenario == "seasonal_ac" else 0.03
    start = datetime(*start_local, tzinfo=IST)
    history: dict[datetime, float] = {}
    t = start.astimezone(timezone.utc)
    for i in range(days * 24):
        local = t.astimezone(IST)
        day_index = i // 24
        dow, hour = local.isoweekday(), local.hour
        base = 0.45
        work = 0.0
        if dow <= 5 and 9 <= hour < 18:
            work = 5.0 + (0.4 if dow == 1 else 0.0) - (1.5 if hour == 13 else 0.0)
        if scenario == "trend_regime":
            work *= 1 + 0.001 * day_index
            if day_index >= REGIME_CHANGE_DAY:
                base += 0.25
                if dow == 6 and 9 <= hour < 13:
                    work += 3.0
        if scenario == "seasonal_ac" and work > 0:
            doy = local.timetuple().tm_yday
            work += 2.5 * max(0.0, sin(2 * pi * (doy - 60) / 365))
        value = max(0.0, (base + work) * (1 + rng.gauss(0, noise)))
        if rng.random() >= missing:
            history[t] = value
        t += timedelta(hours=1)
    return TrainingSeries(
        series_id=f"synthetic-{scenario}-{seed}",
        tz=IST,
        working_days={1, 2, 3, 4, 5},
        provenance={
            "synthetic": True,
            "source": "app.training.synthetic",
            "description": f"SYNTHETIC generated office load, scenario {scenario} (not measured data)",
            "scenario": scenario,
            "seed": seed,
        },
        history=history,
    )
