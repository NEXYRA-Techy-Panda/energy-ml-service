"""Parsing and validation for POST /v1/anomalies.

Order: body size (413) → JSON (NaN/Infinity rejected) → contract_version →
per-section record bounds (413) → forbidden fault fields anywhere → closed
models → reference/evaluation separation → per-section P010 semantic checks
(timestamps, window containment, references, policy effectivity, energy
consistency, overlaps; identical duplicates deduplicated so they cannot
inflate support; conflicting duplicates rejected). Error fields are prefixed
with the section ("reference." / "evaluation.").
"""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from ..analysis.models import AnalyzeRequest, DeviceInterval, Options, RoomInterval
from ..analysis.validate import ParsedRequest, _find_forbidden, _loc, _semantic_checks, epoch
from ..config import CONTRACT_VERSION
from ..errors import ApiError
from .constants import DETECTOR_VERSION, MAX_BODY_BYTES, MAX_DEVICE_INTERVALS_PER_SECTION, MAX_ROOM_INTERVALS_PER_SECTION
from .models import AnomalyRequest


@dataclass
class SectionData:
    start: int
    end: int
    room_intervals: list[RoomInterval]
    device_intervals: list[DeviceInterval]
    duplicates_deduped: int


@dataclass
class ParsedAnomalyRequest:
    request: AnomalyRequest
    reference: SectionData
    evaluation: SectionData


def _reject_constant(name: str) -> float:
    raise ValueError(f"non-finite number {name} is not allowed")


def parse_anomaly_request(raw: bytes, detector_version: str = DETECTOR_VERSION) -> ParsedAnomalyRequest:
    """Shared by /v1/anomalies (default version) and /v1/drift (its own version)."""
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

    for section in ("reference", "evaluation"):
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for key, bound in (("device_intervals", MAX_DEVICE_INTERVALS_PER_SECTION), ("room_intervals", MAX_ROOM_INTERVALS_PER_SECTION)):
            records = block.get(key)
            if isinstance(records, list) and len(records) > bound:
                raise ApiError(413, "REQUEST_TOO_LARGE",
                               f"{section}.{key} has {len(records)} records; the bound is {bound} per section", f"{section}.{key}")

    forbidden = _find_forbidden(data, "")
    if forbidden:
        raise ApiError(400, "VALIDATION_ERROR", f"Injected-fault field {forbidden.rsplit('.', 1)[-1]!r} is forbidden in detector inputs", forbidden)

    try:
        req = AnomalyRequest.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(400, "VALIDATION_ERROR", first["msg"], _loc(first["loc"]) or None) from None
    if req.detector is not None and req.detector.version != detector_version:
        raise ApiError(400, "VALIDATION_ERROR", f"detector.version {req.detector.version!r} is not available (use {detector_version!r})", "detector.version")

    ref_end = epoch(req.reference.window.end_utc, "reference.window.end_utc")
    eval_start = epoch(req.evaluation.window.start_utc, "evaluation.window.start_utc")
    if ref_end > eval_start:
        raise ApiError(400, "VALIDATION_ERROR",
                       "reference.window must end at or before evaluation.window starts (no future reference data)", "reference.window.end_utc")

    return ParsedAnomalyRequest(req, _section(req, "reference"), _section(req, "evaluation"))


def _section(req: AnomalyRequest, name: str) -> SectionData:
    sec = getattr(req, name)
    as_analysis = AnalyzeRequest.model_construct(
        contract_version=req.contract_version, dataset_id=req.dataset_id, run_id=req.run_id, window=sec.window,
        rooms=req.rooms, devices=req.devices, policies=req.policies, room_intervals=sec.room_intervals,
        device_intervals=sec.device_intervals, options=Options())
    parsed = ParsedRequest(as_analysis, [], [])
    try:
        _semantic_checks(parsed)  # the unchanged P010 semantic validation, applied per section
    except ApiError as exc:
        if exc.field and exc.field.startswith(("room_intervals", "device_intervals", "window")):
            exc.field = f"{name}.{exc.field}"
        raise
    return SectionData(epoch(sec.window.start_utc, ""), epoch(sec.window.end_utc, ""),
                       parsed.room_intervals, parsed.device_intervals, parsed.duplicates_deduped)
