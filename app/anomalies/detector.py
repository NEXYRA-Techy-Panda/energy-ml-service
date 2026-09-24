"""Excess-consumption deviation detector ("excess-power-mad-v1").

For each device, evaluation intervals are compared ONLY with the same device's
own comparable REFERENCE intervals (the evaluation section never contributes
to a baseline):

Comparability (MVP):
- fully on (on_fraction == 1); off and mixed-duty intervals are excluded and
  never divided by on_fraction; missing on_fraction → excluded (duty unknown);
- not partial; same interval_seconds (resolution);
- power is the device's own avg_power_w — the whole device/group rating,
  never multiplied by quantity; devices are never compared with each other;
- comfort-dependent equipment (ac, refrigerator): reference intervals must
  also have room temperature within ±TEMP_BAND_C and occupancy_avg within
  ±OCCUPANCY_BAND of the evaluated interval's room; without room context the
  interval is excluded (unsupported context). A temperature or occupancy
  change alone therefore never produces a finding;
- policy versions change WHEN a device runs, not its fully-on power, so they
  are not a comparability factor (policy refs are reported as evidence).

Baseline: median m of comparable reference power; robust spread
s = 1.4826 × MAD; threshold = m + max(4 s, max(10 W, 10 % × m)). Zero MAD
(constant reference) uses the floor — no division by zero. Requires >= 12
reference intervals spanning >= 2 h. Only UPWARD exceedances are findings.
Missing readings are absent, never zero.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median

from ..analysis.models import Device, DeviceInterval, RoomInterval
from ..analysis.validate import epoch
from .constants import (
    ABS_FLOOR_W, COMFORT_DEPENDENT_TYPES, DETECTOR_VERSION, FINDING_TYPE, FULL_ON_TOLERANCE, MAD_SCALE,
    MAX_EXCLUSIONS_LISTED, MIN_REFERENCE_SPAN_HOURS, MIN_REFERENCE_SUPPORT, OCCUPANCY_BAND, REL_FLOOR, TEMP_BAND_C,
    THRESHOLD_K,
)
from .validate import ParsedAnomalyRequest, SectionData


def utc(t: int) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Obs:
    start: int
    end: int
    seconds: int
    power: float
    interval: DeviceInterval
    temp: float | None = None
    occupancy: float | None = None


@dataclass
class Baseline:
    support: int
    span_hours: float
    median_w: float
    mad_w: float
    robust_sigma_w: float
    threshold_w: float

    def as_dict(self) -> dict:
        return {"support": self.support, "span_hours": round(self.span_hours, 3), "median_w": self.median_w,
                "mad_w": self.mad_w, "robust_sigma_w": self.robust_sigma_w, "threshold_w": self.threshold_w}


def fit_baseline(obs: list[Obs]) -> tuple[Baseline | None, str | None]:
    """Robust reference distribution; returns (baseline, None) or (None, reason)."""
    if len(obs) < MIN_REFERENCE_SUPPORT:
        return None, f"{len(obs)} comparable reference intervals (needs {MIN_REFERENCE_SUPPORT})"
    span = (max(o.end for o in obs) - min(o.start for o in obs)) / 3600
    if span < MIN_REFERENCE_SPAN_HOURS:
        return None, f"comparable reference spans {span:.2f} h (needs {MIN_REFERENCE_SPAN_HOURS} h)"
    powers = [o.power for o in obs]
    m = median(powers)
    mad = median(abs(p - m) for p in powers)
    sigma = MAD_SCALE * mad
    margin = max(THRESHOLD_K * sigma, max(ABS_FLOOR_W, REL_FLOOR * m))
    return Baseline(len(obs), span, m, mad, sigma, m + margin), None


@dataclass
class DeviceResult:
    device: Device
    evaluated: int = 0
    flagged: list[tuple[Obs, Baseline]] = field(default_factory=list)
    insufficient: int = 0
    insufficient_reasons: dict[str, int] = field(default_factory=dict)
    excluded: dict[str, int] = field(default_factory=dict)
    reference_excluded: dict[str, int] = field(default_factory=dict)
    reference_usable: int = 0
    baselines: dict[str, dict] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.flagged:
            return "deviation_found"
        if self.evaluated:
            return "evaluated_no_deviation"
        if self.insufficient:
            return "insufficient_reference"
        if self.excluded.get("no_room_context"):
            return "unsupported_context"
        return "no_comparable_observations"


def _room_context(section: SectionData) -> dict[tuple[str, int], RoomInterval]:
    return {(r.room_id, epoch(r.interval_start_utc, "")): r for r in section.room_intervals}


def _classify(d: DeviceInterval, device: Device, rooms: dict) -> tuple[Obs | None, str | None]:
    """Returns (comparable observation, None) or (None, exclusion reason)."""
    if d.on_fraction is None:
        return None, "duty_unknown"
    if d.on_fraction <= 0:
        return None, "off"
    if d.on_fraction < 1 - FULL_ON_TOLERANCE:
        return None, "mixed_duty"
    if d.partial:
        return None, "partial_interval"
    s = epoch(d.interval_start_utc, "")
    obs = Obs(s, epoch(d.interval_end_utc, ""), d.interval_seconds, d.avg_power_w, d)
    if device.device_type in COMFORT_DEPENDENT_TYPES:
        room = rooms.get((d.room_id, s))
        if room is None or room.avg_temp_c is None:
            return None, "no_room_context"
        obs.temp, obs.occupancy = room.avg_temp_c, room.occupancy_avg
    return obs, None


def _count(bucket: dict[str, int], key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1


def detect(parsed: ParsedAnomalyRequest) -> dict:
    req = parsed.request
    ref_rooms, eval_rooms = _room_context(parsed.reference), _room_context(parsed.evaluation)
    results = {d.device_id: DeviceResult(d) for d in req.devices}
    exclusions: list[dict] = []
    reference: dict[str, list[Obs]] = {d.device_id: [] for d in req.devices}

    # 1) Reference: comparable observations only (fitted from the reference section alone).
    for d in parsed.reference.device_intervals:
        res = results[d.device_id]
        obs, reason = _classify(d, res.device, ref_rooms)
        if obs is None:
            _count(res.reference_excluded, reason)
            if len(exclusions) < MAX_EXCLUSIONS_LISTED:
                exclusions.append({"section": "reference", "device_id": d.device_id, "interval_start_utc": d.interval_start_utc, "reason": reason})
            continue
        reference[d.device_id].append(obs)
        res.reference_usable += 1

    # Non-comfort devices: one baseline per resolution, fitted once from the reference.
    fitted: dict[tuple[str, int], tuple[Baseline | None, str | None]] = {}
    for dev_id, obs_list in reference.items():
        res = results[dev_id]
        if res.device.device_type in COMFORT_DEPENDENT_TYPES:
            continue
        for seconds in sorted({o.seconds for o in obs_list}):
            base, why = fit_baseline([o for o in obs_list if o.seconds == seconds])
            fitted[(dev_id, seconds)] = (base, why)
            res.baselines[str(seconds)] = base.as_dict() if base else {"insufficient": why}

    # 2) Evaluation.
    for d in parsed.evaluation.device_intervals:
        res = results[d.device_id]
        obs, reason = _classify(d, res.device, eval_rooms)
        if obs is None:
            _count(res.excluded, reason)
            if len(exclusions) < MAX_EXCLUSIONS_LISTED:
                exclusions.append({"section": "evaluation", "device_id": d.device_id, "interval_start_utc": d.interval_start_utc, "reason": reason})
            continue
        if res.device.device_type in COMFORT_DEPENDENT_TYPES:
            comparable = [o for o in reference[d.device_id] if o.seconds == obs.seconds
                          and abs(o.temp - obs.temp) <= TEMP_BAND_C and abs(o.occupancy - obs.occupancy) <= OCCUPANCY_BAND]
            base, why = fit_baseline(comparable)
            if why:
                why = f"no comparable conditions: {why} within ±{TEMP_BAND_C} °C and ±{OCCUPANCY_BAND} occupancy"
        else:
            base, why = fitted.get((d.device_id, obs.seconds), (None, f"no comparable reference at {obs.seconds} s resolution"))
        if base is None:
            res.insufficient += 1
            _count(res.insufficient_reasons, why)
            continue
        res.evaluated += 1
        if obs.power > base.threshold_w:
            res.flagged.append((obs, base))

    findings = [f for res in results.values() for f in _findings(res, req)]
    return {"results": results, "findings": findings, "exclusions": exclusions}


def _findings(res: DeviceResult, req) -> list[dict]:
    groups: list[list[tuple[Obs, Baseline]]] = []
    for item in sorted(res.flagged, key=lambda x: x[0].start):
        if groups and groups[-1][-1][0].end == item[0].start:
            groups[-1].append(item)
        else:
            groups.append([item])
    room_name = next((r.name for r in req.rooms if r.room_id == res.device.room_id), res.device.room_id)
    comfort = res.device.device_type in COMFORT_DEPENDENT_TYPES
    out = []
    for g in groups:
        observed = [o.power for o, _ in g]
        expected = [b.median_w for _, b in g]
        seconds = sum(o.seconds for o, _ in g)
        above_kwh = sum((o.power - b.median_w) * o.seconds for o, b in g) / 3_600_000
        mean_obs, mean_exp = sum(observed) / len(g), sum(expected) / len(g)
        assumptions = [
            f"Compared only with this device's own fully-on reference intervals at {g[0][0].seconds}-second resolution "
            f"(reference {req.reference.window.start_utc} to {req.reference.window.end_utc}).",
            "Power is the device's reported whole-device/group average power; quantity is not applied.",
            f"Threshold = reference median + max({THRESHOLD_K:g} × 1.4826 × MAD, max({ABS_FLOOR_W:g} W, {REL_FLOOR:.0%} of median)).",
            "A power deviation alone does not establish a malfunction, voltage fault or efficiency loss.",
        ]
        if comfort:
            assumptions.append(f"Comfort-dependent equipment: reference limited to intervals with room temperature within ±{TEMP_BAND_C:g} °C "
                               f"and occupancy within ±{OCCUPANCY_BAND:g} of each evaluated interval.")
        out.append({
            "finding_id": f"{FINDING_TYPE}:{res.device.device_id}:{utc(g[0][0].start)}",
            "finding_type": FINDING_TYPE,
            "device_id": res.device.device_id,
            "room_id": res.device.room_id,
            "window_start_utc": utc(g[0][0].start),
            "window_end_utc": utc(g[-1][0].end),
            "intervals": len(g),
            "observed": {"value": mean_obs, "unit": "W", "statistic": "mean avg_power_w over flagged intervals", "max": max(observed)},
            "expected": {"value": mean_exp, "unit": "W", "statistic": "reference median power"},
            "threshold_w": max(b.threshold_w for _, b in g),
            "reference_support": min(b.support for _, b in g),
            "deviation": {"watts": mean_obs - mean_exp, "ratio": (mean_obs / mean_exp) if mean_exp > 0 else None,
                          "robust_z": ((mean_obs - mean_exp) / g[0][1].robust_sigma_w) if g[0][1].robust_sigma_w > 0 else None},
            "energy_above_baseline_kwh": above_kwh,
            "energy_note": "Energy above the reference median over the flagged intervals; NOT a guaranteed avoidable amount.",
            "method": "rule",
            "technique": "robust_median_mad",
            "detector_version": DETECTOR_VERSION,
            "suggested_action": f"Check the {res.device.name} in {room_name}: confirm its schedule/manual state, connected load and "
                                "equipment operation during this window.",
            "assumptions": " ".join(assumptions),
            "resolution_limit": f"{g[0][0].seconds}-second interval averages; sub-interval spikes and duty patterns are not visible.",
            "evidence": {
                "policy_refs": sorted({o.interval.policy_ref for o, _ in g}),
                "intervals": [{"interval_start_utc": o.interval.interval_start_utc, "avg_power_w": o.power, "expected_w": b.median_w,
                               "threshold_w": b.threshold_w, "reference_support": b.support} for o, b in g],
                "flagged_seconds": seconds,
            },
        })
    return out
