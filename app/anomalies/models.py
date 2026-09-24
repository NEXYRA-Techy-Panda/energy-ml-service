"""Request model for POST /v1/anomalies ("excess-power-request-v1", local additive
API extension; the shared contract is not changed). Rooms, devices, policies and
interval records reuse the P010 closed/strict contract-aligned models."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from ..analysis.models import Closed, Device, DeviceInterval, Policy, Room, RoomInterval, Window


class Section(Closed):
    window: Window
    room_intervals: list[RoomInterval]
    device_intervals: list[DeviceInterval]


class DetectorSelector(Closed):
    version: Annotated[str, StringConstraints(min_length=1)]


class AnomalyRequest(Closed):
    contract_version: Literal["1.0.1"]
    dataset_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    run_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    rooms: Annotated[list[Room], Field(min_length=1)]
    devices: Annotated[list[Device], Field(min_length=1)]
    policies: Annotated[list[Policy], Field(min_length=1)]
    reference: Section
    evaluation: Section
    detector: DetectorSelector | None = None
