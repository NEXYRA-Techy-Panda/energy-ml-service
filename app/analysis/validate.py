"""Parsing and semantic validation for POST /v1/analyze.

Order: body size → JSON → contract_version → record bounds (413) →
forbidden fault fields anywhere → closed models → semantic checks
(timestamps, window, references, policy effectivity, duplicates, energy).
Invalid records are rejected, never silently dropped. Identical duplicates
are deduplicated and reported (contract §1); conflicting ones are errors.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import ValidationError

from ..config import CONTRACT_VERSION
from ..errors import ApiError
from .models import AnalyzeRequest, DeviceInterval, RoomInterval

MAX_DEVICE_INTERVALS = 2000
MAX_ROOM_INTERVALS = 2000
MAX_BODY_BYTES = 8 * 1024 * 1024
ENERGY_TOLERANCE_KWH = 1e-9  # contract §3.6 per-value tolerance
FORBIDDEN_FIELDS = frozenset({
    "fault_active", "fault_type", "fault_window", "fault_windows", "injected_fault",
    "expected_diagnosis", "expected_finding", "is_fault", "fault_label",
})


def epoch(utc: str, field_name: str) -> int:
    try:
        return int(datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        raise ApiError(400, "VALIDATION_ERROR", f"{utc!r} is not a real UTC timestamp", field_name) from None


@dataclass
class ParsedRequest:
    request: AnalyzeRequest
    room_intervals: list[RoomInterval]
    device_intervals: list[DeviceInterval]
    duplicates_deduped: int = 0
    notes: list[str] = field(default_factory=list)


def _find_forbidden(node: object, path: str) -> str | None:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if key in FORBIDDEN_FIELDS:
                return here
            found = _find_forbidden(value, here)
            if found:
                return found
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found = _find_forbidden(value, f"{path}[{i}]")
            if found:
                return found
    return None


def _loc(loc: tuple) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def parse_request(raw: bytes) -> ParsedRequest:
    if len(raw) > MAX_BODY_BYTES:
        raise ApiError(413, "REQUEST_TOO_LARGE", f"Request body exceeds {MAX_BODY_BYTES} bytes; narrow the window")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "VALIDATION_ERROR", "Request body is not valid JSON") from None
    if not isinstance(data, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Request body must be a JSON object")

    version = data.get("contract_version")
    if version is None:
        raise ApiError(400, "VALIDATION_ERROR", "contract_version is required", "contract_version")
    if version != CONTRACT_VERSION:
        raise ApiError(400, "UNSUPPORTED_VERSION", f"contract_version {version!r} is not supported (expected {CONTRACT_VERSION})", "contract_version")

    for key, bound in (("device_intervals", MAX_DEVICE_INTERVALS), ("room_intervals", MAX_ROOM_INTERVALS)):
        records = data.get(key)
        if isinstance(records, list) and len(records) > bound:
            raise ApiError(413, "REQUEST_TOO_LARGE",
                           f"{key} has {len(records)} records; the bound is {bound}. Narrow the window and preserve temporal context.", key)

    forbidden = _find_forbidden(data, "")
    if forbidden:
        raise ApiError(400, "VALIDATION_ERROR", f"Injected-fault field {forbidden.rsplit('.', 1)[-1]!r} is forbidden in analysis inputs", forbidden)

    try:
        req = AnalyzeRequest.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(400, "VALIDATION_ERROR", first["msg"], _loc(first["loc"]) or None) from None

    parsed = ParsedRequest(req, [], [])
    _semantic_checks(parsed)
    return parsed


def _dedupe(records: list, key_fields: tuple[str, str], name: str) -> tuple[list, int]:
    seen: dict[tuple, tuple[int, object]] = {}
    kept, dupes = [], 0
    for i, rec in enumerate(records):
        key = tuple(getattr(rec, k) for k in key_fields)
        if key in seen:
            first_index, first = seen[key]
            if rec != first:
                raise ApiError(400, "VALIDATION_ERROR",
                               f"Conflicting duplicate {name} for {key} (differs from {name}[{first_index}])", f"{name}[{i}]", row=i)
            dupes += 1
            continue
        seen[key] = (i, rec)
        kept.append(rec)
    return kept, dupes


def _semantic_checks(p: ParsedRequest) -> None:
    req = p.request
    w_start = epoch(req.window.start_utc, "window.start_utc")
    w_end = epoch(req.window.end_utc, "window.end_utc")
    if w_end <= w_start:
        raise ApiError(400, "VALIDATION_ERROR", "window.end_utc must be after window.start_utc", "window.end_utc")

    rooms = {}
    for i, r in enumerate(req.rooms):
        if r.room_id in rooms:
            raise ApiError(400, "VALIDATION_ERROR", f"Duplicate room_id {r.room_id!r}", f"rooms[{i}].room_id")
        rooms[r.room_id] = r
    devices = {}
    for i, d in enumerate(req.devices):
        if d.device_id in devices:
            raise ApiError(400, "VALIDATION_ERROR", f"Duplicate device_id {d.device_id!r}", f"devices[{i}].device_id")
        if d.room_id not in rooms:
            raise ApiError(400, "VALIDATION_ERROR", f"Unknown room {d.room_id!r}", f"devices[{i}].room_id")
        devices[d.device_id] = d
    policies = {}
    for i, pol in enumerate(req.policies):
        ref = f"{pol.policy_id}:{pol.version}"
        if ref in policies:
            raise ApiError(400, "VALIDATION_ERROR", f"Duplicate policy version {ref}", f"policies[{i}]")
        if pol.applies_to is not None:
            scope, _, target = pol.applies_to.partition(":")
            known = {"device": devices, "room": rooms}.get(scope)
            if scope not in ("device", "room", "building") or not target or (known is not None and target not in known):
                raise ApiError(400, "VALIDATION_ERROR", f"applies_to {pol.applies_to!r} does not reference a known device, room or building", f"policies[{i}].applies_to")
        if pol.effective_from_utc is not None:
            epoch(pol.effective_from_utc, f"policies[{i}].effective_from_utc")
        policies[ref] = pol
    for i, pol in enumerate(req.policies):
        ref = pol.rules.get("office_hours_ref") if pol.kind == "device_schedule" else None
        if ref is not None and ref in policies and policies[ref].kind != "office_hours":
            raise ApiError(400, "VALIDATION_ERROR", f"office_hours_ref {ref} is not an office_hours policy", f"policies[{i}].rules.office_hours_ref")

    def check_times(name: str, i: int, rec) -> tuple[int, int]:
        s = epoch(rec.interval_start_utc, f"{name}[{i}].interval_start_utc")
        e = epoch(rec.interval_end_utc, f"{name}[{i}].interval_end_utc")
        if e - s != rec.interval_seconds:
            raise ApiError(400, "VALIDATION_ERROR", f"interval_end_utc - interval_start_utc ({e - s} s) must equal interval_seconds ({rec.interval_seconds})", f"{name}[{i}].interval_seconds", row=i)
        if s < w_start or e > w_end:
            raise ApiError(400, "VALIDATION_ERROR", "Interval lies outside the request window", f"{name}[{i}].interval_start_utc", row=i)
        if rec.run_id is not None and rec.run_id != req.run_id:
            raise ApiError(400, "VALIDATION_ERROR", f"Interval run_id {rec.run_id!r} differs from request run_id", f"{name}[{i}].run_id", row=i)
        return s, e

    for i, r in enumerate(req.room_intervals):
        check_times("room_intervals", i, r)
        if r.room_id not in rooms:
            raise ApiError(400, "VALIDATION_ERROR", f"Unknown room {r.room_id!r}", f"room_intervals[{i}].room_id", row=i)
        if r.occupancy_max < r.occupancy_avg - 1e-9:
            raise ApiError(400, "VALIDATION_ERROR", "occupancy_max is below occupancy_avg", f"room_intervals[{i}].occupancy_max", row=i)
        if r.occupancy_max == 0 and (r.occupancy_avg > 0 or r.occupied_fraction > 0):
            raise ApiError(400, "VALIDATION_ERROR", "A room with occupancy_max 0 cannot have occupancy", f"room_intervals[{i}].occupied_fraction", row=i)

    for i, d in enumerate(req.device_intervals):
        s, _ = check_times("device_intervals", i, d)
        where = f"device_intervals[{i}]"
        dev = devices.get(d.device_id)
        if dev is None:
            raise ApiError(400, "VALIDATION_ERROR", f"Unknown device {d.device_id!r}", f"{where}.device_id", row=i)
        if d.room_id != dev.room_id:
            raise ApiError(400, "VALIDATION_ERROR", f"Device {d.device_id!r} belongs to {dev.room_id!r}, not {d.room_id!r}", f"{where}.room_id", row=i)
        pol = policies.get(d.policy_ref)
        if pol is None:
            raise ApiError(400, "VALIDATION_ERROR", f"policy_ref {d.policy_ref} does not resolve to a supplied policy version", f"{where}.policy_ref", row=i)
        if pol.applies_to is not None and pol.applies_to != f"device:{d.device_id}":
            raise ApiError(400, "VALIDATION_ERROR", f"policy {d.policy_ref} applies to {pol.applies_to}, not device {d.device_id}", f"{where}.policy_ref", row=i)
        if pol.effective_from_utc is not None and epoch(pol.effective_from_utc, "") > s:
            raise ApiError(400, "VALIDATION_ERROR",
                           f"policy {d.policy_ref} is effective from {pol.effective_from_utc}, after this interval starts (a future policy cannot apply retroactively)", f"{where}.policy_ref", row=i)
        expected_kwh = d.avg_power_w * d.interval_seconds / 3_600_000
        if abs(d.energy_kwh - expected_kwh) > ENERGY_TOLERANCE_KWH:
            raise ApiError(400, "VALIDATION_ERROR",
                           f"energy_kwh {d.energy_kwh} is inconsistent with avg_power_w x interval_seconds ({expected_kwh})", f"{where}.energy_kwh", row=i)
        if d.max_power_w is not None and d.max_power_w < d.avg_power_w - 1e-9:
            raise ApiError(400, "VALIDATION_ERROR", "max_power_w is below avg_power_w", f"{where}.max_power_w", row=i)
        for name in ("vacant_on_seconds", "offschedule_on_seconds", "override_seconds"):
            value = getattr(d, name)
            if value is not None and value > d.interval_seconds + 1e-9:
                raise ApiError(400, "VALIDATION_ERROR", f"{name} exceeds interval_seconds", f"{where}.{name}", row=i)
        if d.on_fraction is not None and d.vacant_on_seconds > d.on_fraction * d.interval_seconds + 1e-6:
            raise ApiError(400, "VALIDATION_ERROR", "vacant_on_seconds exceeds the on-time implied by on_fraction", f"{where}.vacant_on_seconds", row=i)

    p.room_intervals, room_dupes = _dedupe(req.room_intervals, ("room_id", "interval_start_utc"), "room_intervals")
    p.device_intervals, device_dupes = _dedupe(req.device_intervals, ("device_id", "interval_start_utc"), "device_intervals")
    p.duplicates_deduped = room_dupes + device_dupes
    for name, records in (("room_intervals", p.room_intervals), ("device_intervals", p.device_intervals)):
        key = "room_id" if name == "room_intervals" else "device_id"
        by_entity: dict[str, list[tuple[int, int]]] = {}
        for rec in records:
            by_entity.setdefault(getattr(rec, key), []).append(
                (epoch(rec.interval_start_utc, ""), epoch(rec.interval_end_utc, "")))
        for entity, spans in by_entity.items():
            spans.sort()
            for (s1, e1), (s2, _) in zip(spans, spans[1:]):
                if s2 < e1:
                    raise ApiError(400, "VALIDATION_ERROR", f"Overlapping {name} for {entity!r}", name)
