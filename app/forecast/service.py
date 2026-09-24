"""POST /v1/forecast orchestration: validate → horizon → baseline → response."""

from datetime import timedelta

from .baseline import LEVELS, forecast, horizon_bounds
from .constants import BASELINE_VERSION, METHOD, MIN_OBSERVED_HOURS, MIN_SUPPORT, STALE_AFTER_HOURS
from .validate import fmt_utc, parse_forecast

HOUR = timedelta(hours=1)

LIMITATIONS = [
    "Statistical profile baseline, not a trained model; no accuracy claim is made for this building.",
    "No prediction interval or confidence is produced (uncertainty: unavailable).",
    "Holidays, historical calendar changes, trends and one-off events are not modelled.",
    "Weather, occupancy and schedule assumptions do not influence the result.",
]


def run_forecast(raw: bytes) -> dict:
    parsed = parse_forecast(raw)
    req, tz, origin, history = parsed.request, parsed.tz, parsed.origin, parsed.history
    working_days = set(req.calendar.working_days_iso)
    hz = horizon_bounds(req.horizon, origin, tz)
    points = forecast(history, hz, tz, working_days, req.horizon)

    warnings: list[dict] = []
    span_start = min(history)
    span_end = max(history) + HOUR
    span_hours = int((span_end - span_start).total_seconds() // 3600)
    missing = span_hours - len(history)
    if missing:
        warnings.append({"code": "MISSING_HOURS",
                         "message": f"{missing} hour(s) between {fmt_utc(span_start)} and {fmt_utc(span_end)} have no observation; they were "
                                    "excluded (not treated as zero)."})
    if parsed.duplicates_deduped:
        warnings.append({"code": "DUPLICATES_DEDUPED",
                         "message": f"{parsed.duplicates_deduped} identical duplicate observation(s) were deduplicated."})
    stale = int((origin - span_end).total_seconds() // 3600)
    if stale > STALE_AFTER_HOURS:
        warnings.append({"code": "STALE_HISTORY",
                         "message": f"The latest observation ends {stale} h before the origin; the profile may not reflect recent operation."})
    gap = int((hz.start - origin).total_seconds() // 3600)
    if gap:
        warnings.append({"code": "GAP_BEFORE_HORIZON",
                         "message": f"{gap} hour(s) between the origin and the start of the next calendar month are not forecast and no "
                                    "observations are invented for them."})
    basis_counts = {level: sum(1 for p in points if p.basis == level) for level in LEVELS}
    if basis_counts["day_class_hour"]:
        warnings.append({"code": "FALLBACK_DAY_CLASS",
                         "message": f"{basis_counts['day_class_hour']} hour(s) used the working/non-working day-class profile because the "
                                    "same weekday/hour had too few observations."})
    if basis_counts["hour_of_day"]:
        warnings.append({"code": "FALLBACK_HOUR_OF_DAY",
                         "message": f"{basis_counts['hour_of_day']} hour(s) used the all-days hour-of-day profile (weakest fallback)."})

    not_used = ["calendar.open_local", "calendar.close_local"]
    if req.calendar.overnight is not None:
        not_used.append("calendar.overnight")
    recorded: dict = {}
    fa = req.future_assumptions
    if fa is not None and fa.schedule is not None:
        not_used.append("future_assumptions.schedule")
        recorded["schedule"] = fa.schedule.model_dump(exclude_none=True)
    if fa is not None and fa.environment is not None:
        not_used.append("future_assumptions.environment")
        recorded["environment"] = fa.environment.model_dump()
    warnings.append({"code": "INPUTS_NOT_USED",
                     "message": "Accepted and recorded but not used by the baseline: " + ", ".join(not_used) + ". Only the observed hourly "
                                "history and calendar.timezone/working_days_iso influence the forecast."})

    return {
        "horizon": req.horizon,
        "origin_utc": req.origin_utc,
        "model_version": None,
        "baseline_version": BASELINE_VERSION,
        "method": METHOD,
        "timezone": req.calendar.timezone,
        "horizon_start_utc": fmt_utc(hz.start),
        "horizon_end_utc": fmt_utc(hz.end),
        "points": [
            {"start_utc": fmt_utc(p.start), "energy_kwh": p.energy_kwh, "basis": p.basis, "support": p.support}
            for p in points
        ],
        "total_energy_kwh": sum(p.energy_kwh for p in points),
        "uncertainty": "unavailable",
        "history_coverage": {
            "observed_hours": len(history),
            "span_start_utc": fmt_utc(span_start),
            "span_end_utc": fmt_utc(span_end),
            "span_hours": span_hours,
            "missing_hours": missing,
            "duplicates_deduped": parsed.duplicates_deduped,
            "min_observed_hours_required": MIN_OBSERVED_HOURS[req.horizon],
        },
        "basis_counts": basis_counts,
        "assumptions": [
            f"Hourly grid anchored at origin_utc; local weekday/hour in {req.calendar.timezone}.",
            f"Day class from calendar.working_days_iso {sorted(working_days)}, applied to history and horizon alike.",
            "Each hour = median of observed history in the first supported level: same weekday+hour (>= "
            f"{MIN_SUPPORT['weekday_hour']} obs), same day-class+hour (>= {MIN_SUPPORT['day_class_hour']}), same hour (>= "
            f"{MIN_SUPPORT['hour_of_day']}).",
            "Missing history hours are excluded, never treated as zero.",
        ],
        "assumptions_recorded": recorded,
        "limitations": LIMITATIONS,
        "warnings": warnings,
    }
