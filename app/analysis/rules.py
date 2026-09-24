"""Deterministic rule: an eligible device operated while its room was vacant
beyond its vacancy grace period ("vacant_but_on").

Method: rule (no model, no probabilities). Evidence comes only from the
supplied room/device intervals and the policy version each device interval
references (the version actually applied; never a later one).

Conservative reasoning at interval resolution:
- A room interval is "fully vacant" only when occupancy_max == 0. Mixed
  intervals (some occupancy) never count as vacant; if the device ran while
  partly vacant, a MIXED_OCCUPANCY warning is returned instead of a finding.
- Vacancy start = start of the earliest contiguous fully vacant room
  interval ending at the analysed one. That is a LOWER BOUND on how long the
  room was vacant, so waste is never overstated. If the vacant run reaches
  the start of the supplied data (or a gap), vacancy may have begun earlier:
  an INSUFFICIENT_VACANCY_CONTEXT warning marks the undetermined part.
- Grace expiry = vacancy start + vacancy_grace_seconds. Only on-time after
  expiry counts. Zero grace applies to the whole fully vacant interval.
- Avoidable energy is estimated only when supported: the device's off-state
  (standby) draw is known and either the whole interval is beyond grace, or
  the device was on for the whole interval (constant-power assumption).
  Otherwise the finding reports observed seconds without an estimate.
- Manual overrides are described, not judged.
- Always-on exceptions (device always_on or an always_on policy) are excluded.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import AnalyzeRequest, Device, DeviceInterval, Policy, RoomInterval
from .validate import epoch

RULE_ID = "vacant_but_on"
RULE_VERSION = "vacant-beyond-grace-v1"
ELIGIBLE_KINDS = ("lighting_schedule", "device_schedule")


def utc(t: int) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Portion:
    """One device interval's contribution to a finding."""

    interval: DeviceInterval
    start: int  # first second counted beyond grace
    end: int
    on_beyond_seconds: float  # guaranteed on-time beyond grace
    observed_kwh: float | None
    expected_kwh: float | None
    grace: int
    vacancy_from: int


@dataclass
class Result:
    findings: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)


def _warning(code: str, message: str, **context) -> dict:
    return {"code": code, "message": message, **context}


def run_rule(req: AnalyzeRequest, room_intervals: list[RoomInterval], device_intervals: list[DeviceInterval]) -> Result:
    result = Result()
    policies = {f"{p.policy_id}:{p.version}": p for p in req.policies}
    rooms = {r.room_id: r for r in req.rooms}
    room_series: dict[str, list[tuple[int, int, RoomInterval]]] = {}
    for r in room_intervals:
        room_series.setdefault(r.room_id, []).append((epoch(r.interval_start_utc, ""), epoch(r.interval_end_utc, ""), r))
    for series in room_series.values():
        series.sort(key=lambda x: x[0])
    by_device: dict[str, list[DeviceInterval]] = {}
    for d in device_intervals:
        by_device.setdefault(d.device_id, []).append(d)

    for device in req.devices:
        intervals = sorted(by_device.get(device.device_id, []), key=lambda d: d.interval_start_utc)
        if device.always_on or any(policies[d.policy_ref].kind == "always_on" for d in intervals):
            result.excluded.append({"device_id": device.device_id, "reason": "always-on exception: vacant operation is by design"})
            continue
        portions: list[Portion] = []
        for d in intervals:
            portion = _evaluate(device, d, policies[d.policy_ref], room_series.get(device.room_id, []), result)
            if portion:
                portions.append(portion)
        for group in _group(portions):
            result.findings.append(_finding(device, rooms[device.room_id].name, group, req.options.tariff_inr_per_kwh))
    return result


def _evaluate(device: Device, d: DeviceInterval, policy: Policy, series, result: Result) -> Portion | None:
    if d.vacant_on_seconds <= 0:
        return None
    s, e = epoch(d.interval_start_utc, ""), epoch(d.interval_end_utc, "")
    ctx = {"device_id": device.device_id, "room_id": device.room_id, "window_start_utc": d.interval_start_utc, "window_end_utc": d.interval_end_utc}
    if policy.kind not in ELIGIBLE_KINDS:
        result.warnings.append(_warning("UNSUPPORTED_POLICY_KIND", f"Policy {d.policy_ref} ({policy.kind}) has no vacancy grace; not evaluated.", **ctx))
        return None
    idx = next((i for i, (rs, re_, _) in enumerate(series) if rs == s and re_ == e), None)
    if idx is None:
        result.warnings.append(_warning("NO_ROOM_INTERVAL", "No room interval with the same boundaries; vacancy cannot be established.", **ctx))
        return None
    room = series[idx][2]
    if room.occupancy_max > 0:
        result.warnings.append(_warning("MIXED_OCCUPANCY",
                                        f"Device ran {d.vacant_on_seconds:g} s while the room was vacant within a partly occupied interval; "
                                        "sub-interval timing cannot establish grace expiry, so no waste is claimed.", **ctx))
        return None

    # Earliest contiguous fully vacant room interval ending here (lower bound on vacancy start).
    k = idx
    while k > 0 and series[k - 1][1] == series[k][0] and series[k - 1][2].occupancy_max == 0:
        k -= 1
    vacancy_from = series[k][0]
    observed_transition = k > 0 and series[k - 1][1] == series[k][0]  # preceded by a contiguous occupied interval
    grace = int(policy.rules["vacancy_grace_seconds"])
    expiry = vacancy_from + grace
    beyond_start = max(s, expiry)
    within = beyond_start - s  # seconds of this interval not (provably) beyond grace

    if not observed_transition and grace > 0 and s < expiry:
        result.warnings.append(_warning(
            "INSUFFICIENT_VACANCY_CONTEXT",
            f"The room is vacant from the start of the supplied data ({utc(vacancy_from)}); vacancy may have begun earlier, so the "
            f"first {grace} s of grace cannot be confirmed as elapsed. Only operation after {utc(expiry)} is counted.", **ctx))
    if beyond_start >= e:
        return None  # grace not (provably) elapsed within this interval

    # Fully vacant interval: all on-time is vacant on-time.
    on = min(d.vacant_on_seconds, d.interval_seconds)
    on_beyond = max(0.0, on - within)
    if on_beyond <= 0:
        result.warnings.append(_warning("SUB_INTERVAL_TIMING",
                                        "The device ran only part of an interval that straddles grace expiry; timing within the interval is unknown.", **ctx))
        return None

    observed = expected = None
    standby = device.standby_power_w
    if standby is not None:
        if within == 0:  # whole interval beyond grace: energy if off would have been standby for the whole interval
            observed = d.energy_kwh
            expected = standby * d.interval_seconds / 3_600_000
        elif on >= d.interval_seconds:  # on throughout a straddling interval: constant-power assumption
            beyond = e - beyond_start
            observed = d.avg_power_w * beyond / 3_600_000
            expected = standby * beyond / 3_600_000
    return Portion(d, beyond_start, e, on_beyond, observed, expected, grace, vacancy_from)


def _group(portions: list[Portion]) -> list[list[Portion]]:
    """Contiguous portions with the same support status form one finding."""
    groups: list[list[Portion]] = []
    for p in portions:
        last = groups[-1][-1] if groups else None
        if last and last.end == p.start and (last.observed_kwh is None) == (p.observed_kwh is None):
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def _finding(device: Device, room_name: str, group: list[Portion], tariff: float | None) -> dict:
    first, last = group[0], group[-1]
    refs = sorted({p.interval.policy_ref for p in group})
    graces = sorted({p.grace for p in group})
    supported = all(p.observed_kwh is not None for p in group)
    on_seconds = sum(p.on_beyond_seconds for p in group)
    override = sum(p.interval.override_seconds or 0 for p in group)
    interval_seconds = sorted({p.interval.interval_seconds for p in group})

    assumptions = [
        "Vacancy is taken from room intervals with occupancy_max = 0; the vacancy start is the start of the earliest contiguous "
        f"fully vacant interval (a conservative lower bound; vacant from {utc(first.vacancy_from)} or earlier).",
        f"Vacancy grace {', '.join(f'{g} s' for g in graces)} from the applied policy version(s) {', '.join(refs)}.",
    ]
    if supported:
        standby = device.standby_power_w or 0.0
        assumptions.append(f"Avoidable energy = observed energy minus the off-state draw ({standby:g} W standby) over the same time.")
        if any(p.start > epoch(p.interval.interval_start_utc, "") for p in group):
            assumptions.append("Where grace expired inside an interval, power is assumed constant within that interval.")
    else:
        assumptions.append("Energy for the beyond-grace portion is not determinable at this resolution (partial operation or unknown "
                           "standby draw); observed operating seconds are reported without an avoidable-energy estimate.")
    if override > 0:
        assumptions.append(f"The device was under manual override for {override:g} s in this window; the rule reports the observed "
                           "condition only and does not judge whether the override was intended.")

    grace_text = ("as soon as it becomes vacant (0-second grace)" if graces == [0]
                  else f"once its {graces[-1]}-second vacancy grace period has elapsed")
    finding = {
        "finding_id": f"{RULE_ID}:{device.device_id}:{utc(first.start)}",
        "finding_type": RULE_ID,
        "room_id": device.room_id,
        "device_id": device.device_id,
        "window_start_utc": utc(first.start),
        "window_end_utc": utc(last.end),
        "observed": ({"value": sum(p.observed_kwh for p in group), "unit": "kWh"} if supported
                     else {"value": on_seconds, "unit": "s"}),
        "expected": ({"value": sum(p.expected_kwh for p in group), "unit": "kWh"} if supported
                     else {"value": 0, "unit": "s"}),
        "method": "rule",
        "suggested_action": f"Switch off {device.name} ({device.device_id}) in {room_name} when the room is vacant, {grace_text}; "
                            "review its schedule or occupancy-based control.",
        "assumptions": " ".join(assumptions),
        "resolution_limit": f"{'/'.join(str(s) for s in interval_seconds)}-second intervals; sub-interval occupancy and switching "
                            "times are not visible.",
        "evidence": {
            "rule_version": RULE_VERSION,
            "policy_refs": refs,
            "vacant_on_seconds_beyond_grace": on_seconds,
            "intervals": [
                {"interval_start_utc": p.interval.interval_start_utc, "interval_end_utc": p.interval.interval_end_utc,
                 "counted_from_utc": utc(p.start), "vacant_on_seconds": p.interval.vacant_on_seconds,
                 "energy_kwh": p.interval.energy_kwh, "policy_ref": p.interval.policy_ref}
                for p in group
            ],
        },
    }
    if supported:
        avoidable = max(0.0, finding["observed"]["value"] - finding["expected"]["value"])
        finding["avoidable_energy_kwh"] = avoidable
        if tariff is not None:
            finding["avoidable_cost_inr"] = avoidable * tariff
    return finding
