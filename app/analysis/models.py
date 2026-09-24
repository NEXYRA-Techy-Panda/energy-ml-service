"""Request models for POST /v1/analyze (contract 1.0.1, API.md Example A).

Every model is closed (extra fields rejected) and strict (no type coercion).
Required fields follow API.md Example A; other contract interval/inventory
fields are accepted when present and validated with the contract's bounds.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

Id = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Utc = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")]
LocalTime = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
PolicyRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+:[0-9]+$")]
IsoDay = Annotated[int, Field(ge=1, le=7)]
DeviceType = Literal["lighting", "ac", "fan", "refrigerator", "microwave", "projector", "computer", "workstation_group"]
PolicyKind = Literal["office_hours", "lighting_schedule", "device_schedule", "always_on", "occupancy"]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _unique_days(days: list[int]) -> list[int]:
    if len(set(days)) != len(days):
        raise ValueError("ISO weekdays must be unique")
    return days


# ---- kind-specific policy rules (contract $defs; closed) ----


class OfficeHoursRules(Closed):
    working_days_iso: Annotated[list[IsoDay], Field(min_length=1, max_length=7)]
    open_local: LocalTime
    close_local: LocalTime
    overnight: bool

    @field_validator("working_days_iso")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        return _unique_days(v)


class LightingScheduleRules(Closed):
    on_during_hours: bool
    vacancy_grace_seconds: Annotated[int, Field(ge=0, le=3600)]


class OnWindow(Closed):
    days: Annotated[list[IsoDay], Field(min_length=1, max_length=7)]
    start_local: LocalTime
    end_local: LocalTime

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        return _unique_days(v)


class DeviceScheduleRules(Closed):
    office_hours_ref: PolicyRef
    on_windows: list[OnWindow] = []
    vacancy_grace_seconds: Annotated[int, Field(ge=0, le=3600)] = 300
    allow_manual_override: bool = True


class AlwaysOnRules(Closed):
    always_on_exception: bool


class OccupancyRules(Closed):
    mode: Literal["manual", "scheduled"]
    auto_allocate: bool = True


RULE_MODELS: dict[str, type[Closed]] = {
    "office_hours": OfficeHoursRules,
    "lighting_schedule": LightingScheduleRules,
    "device_schedule": DeviceScheduleRules,
    "always_on": AlwaysOnRules,
    "occupancy": OccupancyRules,
}


# ---- request ----


class Window(Closed):
    start_utc: Utc
    end_utc: Utc


class Room(Closed):
    room_id: Id
    name: Annotated[str, StringConstraints(min_length=1)]
    capacity: Annotated[int, Field(ge=0, le=500)]
    room_type: Annotated[str, StringConstraints(min_length=1)] | None = None
    floor_area_m2: Annotated[float, Field(gt=0)] | None = None


class Device(Closed):
    device_id: Id
    name: Annotated[str, StringConstraints(min_length=1)]
    room_id: Id
    device_type: DeviceType
    always_on: bool
    quantity: Annotated[int, Field(ge=1, le=1000)] | None = None
    nominal_power_w: Annotated[float, Field(ge=0, le=100000)] | None = None
    standby_power_w: Annotated[float, Field(ge=0, le=100000)] | None = None
    power_factor: Annotated[float, Field(ge=0.1, le=1.0)] | None = None
    control: Literal["manual", "scheduled", "always_on"] | None = None
    controls: list[str] | None = None


class Policy(Closed):
    policy_id: Id
    version: Annotated[int, Field(ge=1)]
    kind: PolicyKind
    rules: dict[str, Any]
    applies_to: Annotated[str, StringConstraints(min_length=1)] | None = None
    effective_from_utc: Utc | None = None

    @model_validator(mode="after")
    def _rules_match_kind(self) -> "Policy":
        # Validated (closed) rules replace the raw dict, with defaults applied.
        try:
            self.rules = RULE_MODELS[self.kind].model_validate(self.rules).model_dump()
        except ValidationError as exc:
            first = exc.errors()[0]
            path = ".".join(str(part) for part in first["loc"])
            raise ValueError(f"{self.kind} rules{'.' + path if path else ''}: {first['msg']}") from None
        return self


class RoomInterval(Closed):
    room_id: Id
    interval_start_utc: Utc
    interval_end_utc: Utc
    interval_seconds: Annotated[int, Field(ge=1)]
    occupancy_avg: Annotated[float, Field(ge=0, le=1000)]
    occupancy_max: Annotated[int, Field(ge=0, le=1000)]
    occupied_fraction: Annotated[float, Field(ge=0, le=1)]
    run_id: Annotated[str, StringConstraints(min_length=1)] | None = None
    avg_temp_c: Annotated[float, Field(ge=-30, le=60)] | None = None
    avg_rh_pct: Annotated[float, Field(ge=0, le=100)] | None = None
    partial: bool | None = None


class DeviceInterval(Closed):
    device_id: Id
    room_id: Id
    interval_start_utc: Utc
    interval_end_utc: Utc
    interval_seconds: Annotated[int, Field(ge=1)]
    avg_power_w: Annotated[float, Field(ge=0, le=100000)]
    energy_kwh: Annotated[float, Field(ge=0, le=100000)]
    vacant_on_seconds: Annotated[float, Field(ge=0)]
    offschedule_on_seconds: Annotated[float, Field(ge=0)]
    policy_ref: PolicyRef
    run_id: Annotated[str, StringConstraints(min_length=1)] | None = None
    max_power_w: Annotated[float, Field(ge=0, le=100000)] | None = None
    cumulative_kwh: Annotated[float, Field(ge=0, le=100000000)] | None = None
    avg_voltage_v: Annotated[float, Field(ge=0, le=500)] | None = None
    avg_current_a: Annotated[float, Field(ge=0, le=500)] | None = None
    power_factor: Annotated[float, Field(ge=0.1, le=1.0)] | None = None
    on_fraction: Annotated[float, Field(ge=0, le=1)] | None = None
    override_seconds: Annotated[float, Field(ge=0)] | None = None
    partial: bool | None = None


class Options(Closed):
    tariff_inr_per_kwh: Annotated[float, Field(ge=0)] | None = None


class AnalyzeRequest(Closed):
    contract_version: Literal["1.0.1"]
    dataset_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    run_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    window: Window
    rooms: Annotated[list[Room], Field(min_length=1)]
    devices: Annotated[list[Device], Field(min_length=1)]
    policies: Annotated[list[Policy], Field(min_length=1)]
    room_intervals: list[RoomInterval]
    device_intervals: list[DeviceInterval]
    options: Options = Options()
