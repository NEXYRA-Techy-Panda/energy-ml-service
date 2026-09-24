"""Gradual upward power-trend detector ("gradual-power-trend-v1").

Pipeline per device (reference section fits baselines; evaluation section is
only assessed against them):

1. Comparable observations: fully-on, non-partial intervals (P022 rules:
   off / mixed-duty / duty-unknown / partial / no-room-context excluded,
   never divided by on_fraction; power = whole device/group, never x
   quantity); one resolution per device (the most common reference
   interval_seconds; others "resolution_mismatch"); the reference's dominant
   policy_ref only (others "policy_changed" — conservative: a configuration
   change is not attributed to the equipment).
2. Context normalisation: ratio = power / median reference power of the same
   CONTEXT. Context = local hour (Asia/Kolkata) for ordinary devices, so a
   change in which hours are sampled is not mistaken for a trend; for
   comfort-dependent devices (ac, refrigerator) context = (1 °C temperature
   bin, occupied yes/no). A context baseline needs >= 3 distinct reference
   days; observations without one are excluded ("no_reference_for_context").
3. Daily summaries (local date): a day is supported with >= 3 comparable
   observations and >= 1 h fully-on comparable time; its value is the median
   ratio. Many readings in one day still count as ONE day. Missing days are
   gaps: nothing is interpolated, elapsed time uses actual calendar days.
4. Support: reference >= 5 supported days over >= 7 days; evaluation >= 10
   supported days over >= 14 days with >= 50 % of calendar days supported.
5. Classification of the evaluation daily series:
   - trend: Theil–Sen median pairwise slope of daily ratio vs elapsed days;
     change = slope × span;
   - abrupt level change: L1 changepoint split (>= 3 days per side; minimum
     total absolute deviation from segment medians) with a level
     change >= 10 % while each side's own Theil–Sen change is <= 3 % →
     reported as a step, never as gradual drift;
   - sustained upward trend (FINDING): change >= 10 % and >= 10 W (× the
     reference level), chronological thirds' medians strictly increasing
     and >= 75 % of final-third days >= 1.05;
   - upward change not sustained: change >= 10 % but persistence fails;
   - level offset without trend: median ratio >= 1.10 without a qualifying
     trend (elevated from the reference start of the period);
   - otherwise stable. Isolated spike days (ratio >= 1.25) are reported; the
     robust estimator and persistence rule keep a spike from becoming a trend.
No efficiency, fault or savings claim is made; outdoor temperature,
setpoints, delivered output and workload are not observed.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from math import floor
from statistics import median
from zoneinfo import ZoneInfo

from ..analysis.models import Device
from ..anomalies.constants import COMFORT_DEPENDENT_TYPES
from ..anomalies.detector import Obs, _classify, _room_context
from ..anomalies.validate import ParsedAnomalyRequest
from .constants import (
    BUILDING_TIMEZONE, COMFORT_TEMP_BIN_C, FINAL_THIRD_ELEVATED_RATIO, FINAL_THIRD_ELEVATED_SHARE, FINDING_TITLE, FINDING_TYPE,
    MAX_EXCLUSIONS_LISTED, MIN_ABSOLUTE_CHANGE_W, MIN_CONTEXT_REFERENCE_DAYS, MIN_DAY_OBSERVATIONS, MIN_DAY_ON_SECONDS,
    MIN_EVALUATION_DAY_COVERAGE, MIN_EVALUATION_DAYS, MIN_EVALUATION_SPAN_DAYS, MIN_REFERENCE_DAYS, MIN_REFERENCE_SPAN_DAYS,
    MIN_RELATIVE_CHANGE, OFFSET_MIN_RATIO, SPIKE_RATIO, STEP_MAX_WITHIN_SEGMENT, STEP_MIN_CHANGE, STEP_MIN_SEGMENT_DAYS,
    DETECTOR_VERSION,
)

TZ = ZoneInfo(BUILDING_TIMEZONE)


def local_day(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(TZ).date()


def context_key(device: Device, obs: Obs) -> tuple:
    if device.device_type in COMFORT_DEPENDENT_TYPES:
        return ("comfort", floor(obs.temp / COMFORT_TEMP_BIN_C), (obs.occupancy or 0) > 0)
    return ("hour", datetime.fromtimestamp(obs.start, tz=timezone.utc).astimezone(TZ).hour)


def theil_sen(days: list[tuple[float, float]]) -> float:
    """Median pairwise slope of (elapsed_days, value) over pairs with distinct days."""
    slopes = [(b[1] - a[1]) / (b[0] - a[0]) for i, a in enumerate(days) for b in days[i + 1:] if b[0] != a[0]]
    return median(slopes) if slopes else 0.0


@dataclass
class DeviceTrend:
    device: Device
    status: str = "no_comparable_observations"
    classification: str | None = None
    reason: str | None = None
    reference_excluded: dict[str, int] = field(default_factory=dict)
    evaluation_excluded: dict[str, int] = field(default_factory=dict)
    reference_observations: int = 0
    evaluation_observations: int = 0
    reference_days: int = 0
    evaluation_days: int = 0
    evaluation_span_days: int = 0
    reference_level_w: float | None = None
    policy_ref: str | None = None
    resolution_seconds: int | None = None
    contexts: int = 0
    daily: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    spikes: list[str] = field(default_factory=list)


def _count(bucket: dict[str, int], key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1


def _supported_days(items: list[tuple[Obs, float]]) -> dict[date, tuple[float, int]]:
    """Group (obs, value) by local day; keep days with enough observations/time; value = median."""
    by_day: dict[date, list[tuple[Obs, float]]] = {}
    for obs, v in items:
        by_day.setdefault(local_day(obs.start), []).append((obs, v))
    out = {}
    for d, rows in by_day.items():
        if len(rows) >= MIN_DAY_OBSERVATIONS and sum(o.seconds for o, _ in rows) >= MIN_DAY_ON_SECONDS:
            out[d] = (median(v for _, v in rows), len(rows))
    return out


def detect_trends(parsed: ParsedAnomalyRequest) -> dict:
    req = parsed.request
    ref_rooms, eval_rooms = _room_context(parsed.reference), _room_context(parsed.evaluation)
    results = {d.device_id: DeviceTrend(d) for d in req.devices}
    exclusions: list[dict] = []

    def exclude(section: str, res: DeviceTrend, interval, reason: str) -> None:
        _count(res.reference_excluded if section == "reference" else res.evaluation_excluded, reason)
        if len(exclusions) < MAX_EXCLUSIONS_LISTED:
            exclusions.append({"section": section, "device_id": interval.device_id, "interval_start_utc": interval.interval_start_utc, "reason": reason})

    ref_obs: dict[str, list[Obs]] = {d.device_id: [] for d in req.devices}
    eval_obs: dict[str, list[Obs]] = {d.device_id: [] for d in req.devices}
    for section, intervals, rooms, bucket in (("reference", parsed.reference.device_intervals, ref_rooms, ref_obs),
                                              ("evaluation", parsed.evaluation.device_intervals, eval_rooms, eval_obs)):
        for d in intervals:
            res = results[d.device_id]
            obs, reason = _classify(d, res.device, rooms)
            if obs is None:
                exclude(section, res, d, reason)
            else:
                bucket[d.device_id].append(obs)

    for dev_id, res in results.items():
        _assess(res, ref_obs[dev_id], eval_obs[dev_id], exclude)
    return {"results": results, "exclusions": exclusions}


def _assess(res: DeviceTrend, ref: list[Obs], ev: list[Obs], exclude) -> None:
    device = res.device
    if not ref:
        res.status = "no_comparable_observations" if not res.reference_excluded.get("no_room_context") else "unsupported_context"
        res.reason = "no comparable fully-on reference observations"
        return
    # One resolution and one configuration per device (from the reference).
    seconds = max(set(o.seconds for o in ref), key=lambda s: sum(1 for o in ref if o.seconds == s))
    policies = [o.interval.policy_ref for o in ref if o.seconds == seconds]
    policy = max(set(policies), key=policies.count)
    res.resolution_seconds, res.policy_ref = seconds, policy
    kept_ref, kept_ev = [], []
    for section, src, dst in (("reference", ref, kept_ref), ("evaluation", ev, kept_ev)):
        for o in src:
            if o.seconds != seconds:
                exclude(section, res, o.interval, "resolution_mismatch")
            elif o.interval.policy_ref != policy:
                exclude(section, res, o.interval, "policy_changed")
            else:
                dst.append(o)

    # Context baselines from the reference only (>= 3 distinct days per context).
    ctx_values: dict[tuple, list[float]] = {}
    ctx_days: dict[tuple, set[date]] = {}
    for o in kept_ref:
        k = context_key(device, o)
        ctx_values.setdefault(k, []).append(o.power)
        ctx_days.setdefault(k, set()).add(local_day(o.start))
    baselines = {k: median(v) for k, v in ctx_values.items() if len(ctx_days[k]) >= MIN_CONTEXT_REFERENCE_DAYS}
    res.contexts = len(baselines)
    res.reference_level_w = median(o.power for o in kept_ref) if kept_ref else None

    def normalised(section: str, obs: list[Obs]) -> list[tuple[Obs, float]]:
        out = []
        for o in obs:
            base = baselines.get(context_key(device, o))
            if base is None or base <= 0:
                exclude(section, res, o.interval, "no_reference_for_context")
            else:
                out.append((o, o.power / base))
        return out

    ref_norm, ev_norm = normalised("reference", kept_ref), normalised("evaluation", kept_ev)
    res.reference_observations, res.evaluation_observations = len(ref_norm), len(ev_norm)
    ref_days, ev_days = _supported_days(ref_norm), _supported_days(ev_norm)
    res.reference_days, res.evaluation_days = len(ref_days), len(ev_days)

    if not ev_norm:
        context_problem = res.evaluation_excluded.get("no_room_context", 0) + res.evaluation_excluded.get("policy_changed", 0)
        res.status = "unsupported_context" if context_problem else ("insufficient_history" if kept_ev else "no_comparable_observations")
        res.reason = "no evaluation observations comparable with the reference context/configuration"
        return
    ref_span = ((max(ref_days) - min(ref_days)).days + 1) if ref_days else 0
    if len(ref_days) < MIN_REFERENCE_DAYS or ref_span < MIN_REFERENCE_SPAN_DAYS:
        res.status, res.reason = "insufficient_history", (
            f"reference has {len(ref_days)} supported days over {ref_span} days (needs {MIN_REFERENCE_DAYS} over {MIN_REFERENCE_SPAN_DAYS})")
        return
    span = ((max(ev_days) - min(ev_days)).days + 1) if ev_days else 0
    res.evaluation_span_days = span
    coverage = len(ev_days) / span if span else 0.0
    if len(ev_days) < MIN_EVALUATION_DAYS or span < MIN_EVALUATION_SPAN_DAYS or coverage < MIN_EVALUATION_DAY_COVERAGE:
        res.status, res.reason = "insufficient_history", (
            f"evaluation has {len(ev_days)} supported days over {span} days (coverage {coverage:.2f}); needs {MIN_EVALUATION_DAYS} "
            f"over {MIN_EVALUATION_SPAN_DAYS} days with coverage >= {MIN_EVALUATION_DAY_COVERAGE}")
        return

    first = min(ev_days)
    series = sorted(((d - first).days, ev_days[d][0], d, ev_days[d][1]) for d in ev_days)
    res.daily = [{"local_date": d.isoformat(), "elapsed_days": x, "ratio_to_reference": v, "observations": n} for x, v, d, n in series]
    pts = [(x, v) for x, v, _, _ in series]
    slope = theil_sen(pts)
    change = slope * (span - 1)
    level = res.reference_level_w or 0.0
    n = len(pts)
    thirds = [pts[: n // 3], pts[n // 3: 2 * n // 3], pts[2 * n // 3:]]
    third_medians = [median(v for _, v in t) for t in thirds]
    final_elevated = sum(1 for _, v in thirds[2] if v >= FINAL_THIRD_ELEVATED_RATIO) / len(thirds[2])
    med_ratio = median(v for _, v in pts)
    res.spikes = [series[i][2].isoformat() for i, (_, v) in enumerate(pts)
                  if v >= SPIKE_RATIO and not any(abs(j - i) == 1 and pts[j][1] >= SPIKE_RATIO for j in range(n))]

    # Best single split for an abrupt level change: the L1 changepoint, i.e. the split
    # (>= 3 days per side) minimising the total absolute deviation from each segment's median.
    step = None
    best_cost = None
    for k in range(STEP_MIN_SEGMENT_DAYS, n - STEP_MIN_SEGMENT_DAYS + 1):
        a, b = pts[:k], pts[k:]
        ma, mb = median(v for _, v in a), median(v for _, v in b)
        cost = sum(abs(v - ma) for _, v in a) + sum(abs(v - mb) for _, v in b)
        if best_cost is None or cost < best_cost:
            within = max(abs(theil_sen(a) * (a[-1][0] - a[0][0])), abs(theil_sen(b) * (b[-1][0] - b[0][0])))
            best_cost, step = cost, (k, mb - ma, within)
    res.metrics = {
        "theil_sen_ratio_per_day": slope, "relative_change_over_span": change,
        "watts_per_day": slope * level, "watts_change_over_span": change * level,
        "median_ratio": med_ratio, "thirds_median_ratio": third_medians, "final_third_elevated_share": final_elevated,
        "best_step": {"at_local_date": series[step[0]][2].isoformat(), "level_change": step[1], "max_within_segment_change": step[2]}
        if step else None,
    }
    persistent = third_medians[0] < third_medians[1] < third_medians[2] and final_elevated >= FINAL_THIRD_ELEVATED_SHARE
    res.status = "evaluated"
    if step and step[1] >= STEP_MIN_CHANGE and step[2] <= STEP_MAX_WITHIN_SEGMENT:
        res.classification = "abrupt_level_change"
    elif change >= MIN_RELATIVE_CHANGE and change * level >= MIN_ABSOLUTE_CHANGE_W and persistent:
        res.classification = "sustained_upward_trend"
    elif change >= MIN_RELATIVE_CHANGE:
        res.classification = "upward_change_not_sustained"
    elif med_ratio >= OFFSET_MIN_RATIO:
        res.classification = "level_offset_without_trend"
    else:
        res.classification = "stable"


def finding_for(res: DeviceTrend, req) -> dict:
    m = res.metrics
    room_name = next((r.name for r in req.rooms if r.room_id == res.device.room_id), res.device.room_id)
    comfort = res.device.device_type in COMFORT_DEPENDENT_TYPES
    assumptions = [
        "Compared only with this device's own fully-on observations at the same resolution and configuration "
        f"({res.policy_ref}); power is the reported whole-device/group value (quantity not applied).",
        "Each observation is normalised by the reference median of its context (local hour" +
        (", or 1 °C room-temperature bin and occupied state for comfort-dependent equipment" if comfort else "") +
        "), so a change in which hours are sampled is not counted as a trend.",
        "Trend = Theil–Sen median pairwise slope of supported daily median ratios against actual elapsed days; missing days are not filled.",
        "A rising power trend does not establish reduced efficiency, a fault or its cause: delivered output, outdoor conditions, "
        "setpoints and workload are not observed.",
    ]
    if comfort:
        assumptions.append("Comfort-dependent equipment: matching observed room temperature/occupancy reduces confounding but does not "
                           "eliminate unmeasured differences such as outdoor temperature, setpoint or workload.")
    return {
        "finding_id": f"{FINDING_TYPE}:{res.device.device_id}:{res.daily[0]['local_date']}",
        "finding_type": FINDING_TYPE,
        "title": FINDING_TITLE,
        "device_id": res.device.device_id,
        "room_id": res.device.room_id,
        "assessed_period": {"first_local_date": res.daily[0]["local_date"], "last_local_date": res.daily[-1]["local_date"],
                            "span_days": res.evaluation_span_days, "timezone": BUILDING_TIMEZONE},
        "reference_level_w": res.reference_level_w,
        "trend": {"watts_per_day": m["watts_per_day"], "relative_per_day": m["theil_sen_ratio_per_day"],
                  "relative_change_over_period": m["relative_change_over_span"], "watts_change_over_period": m["watts_change_over_span"]},
        "persistence": {"thirds_median_ratio": m["thirds_median_ratio"], "final_third_elevated_share": m["final_third_elevated_share"]},
        "support": {"reference_days": res.reference_days, "evaluation_days": res.evaluation_days,
                    "evaluation_observations": res.evaluation_observations, "reference_observations": res.reference_observations,
                    "evaluation_excluded": res.evaluation_excluded, "reference_excluded": res.reference_excluded},
        "method": "rule",
        "technique": "theil_sen_context_normalised_daily",
        "detector_version": DETECTOR_VERSION,
        "suggested_action": f"Investigate the {res.device.name} in {room_name}: compare settings, connected load, maintenance state and "
                            "operating conditions over this period before attributing a cause.",
        "assumptions": " ".join(assumptions),
        "limitations": "Not an efficiency or fault diagnosis; no avoidable-energy, savings or ROI estimate; must not be added to "
                       "vacancy or excess-consumption findings.",
        "evidence": {"daily": res.daily, "spike_days": res.spikes},
    }
