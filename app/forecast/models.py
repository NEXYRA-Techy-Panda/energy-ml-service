"""Request models for POST /v1/forecast (contract 1.0.1, API.md Example B).

Closed and strict, like /v1/analyze. Fields follow Example B exactly:
contract_version, dataset_id, origin_utc, horizon, history_hourly_kwh
[{start_utc, energy_kwh}], calendar {timezone, working_days_iso,
open_local, close_local}, future_assumptions {schedule, environment},
model {version}. Local clarification: calendar.overnight is optional;
future_assumptions and model are optional.
"""

import math
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from ..analysis.models import Closed, IsoDay, LocalTime, Policy, Utc


class HourPoint(Closed):
    """One observed, complete hour [start_utc, start_utc + 1 h). No partial hours."""

    start_utc: Utc
    energy_kwh: Annotated[float, Field(ge=0, le=1_000_000)]

    @field_validator("energy_kwh")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("energy_kwh must be finite")
        return v


class Calendar(Closed):
    timezone: Annotated[str, StringConstraints(min_length=1)]
    working_days_iso: Annotated[list[IsoDay], Field(min_length=1, max_length=7)]
    open_local: LocalTime
    close_local: LocalTime
    overnight: bool | None = None

    @field_validator("working_days_iso")
    @classmethod
    def _unique(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("ISO weekdays must be unique")
        return v


class Environment(Closed):
    avg_temp_c: Annotated[float, Field(ge=-30, le=60)]
    avg_rh_pct: Annotated[float, Field(ge=0, le=100)]


class FutureAssumptions(Closed):
    schedule: Policy | None = None
    environment: Environment | None = None


class ModelSelector(Closed):
    version: Annotated[str, StringConstraints(min_length=1)]


class ForecastRequest(Closed):
    contract_version: Literal["1.0.1"]
    dataset_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    origin_utc: Utc
    horizon: Literal["next_24h", "next_7d", "next_calendar_month"]
    history_hourly_kwh: list[HourPoint]
    calendar: Calendar
    future_assumptions: FutureAssumptions | None = None
    model: ModelSelector | None = None
