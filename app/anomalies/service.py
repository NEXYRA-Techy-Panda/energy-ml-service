"""POST /v1/anomalies orchestration: validate → detect → honest status + coverage."""

from .constants import (
    ABS_FLOOR_W, COMFORT_DEPENDENT_TYPES, DETECTOR_VERSION, MAD_SCALE, MAX_DEVICE_INTERVALS_PER_SECTION,
    MAX_EXCLUSIONS_LISTED, MAX_ROOM_INTERVALS_PER_SECTION, MIN_REFERENCE_SPAN_HOURS, MIN_REFERENCE_SUPPORT, OCCUPANCY_BAND,
    REL_FLOOR, REQUEST_FORMAT, TEMP_BAND_C, THRESHOLD_K,
)
from .detector import detect
from .validate import parse_anomaly_request

STATUS_ORDER = ("findings_detected", "evaluated_no_deviation", "insufficient_reference", "unsupported_context", "no_comparable_observations")


def run_anomalies(raw: bytes) -> dict:
    parsed = parse_anomaly_request(raw)
    req = parsed.request
    out = detect(parsed)
    results = out["results"]

    devices = []
    totals = {"evaluation_device_intervals": len(parsed.evaluation.device_intervals), "evaluated": 0, "flagged": 0,
              "insufficient_reference": 0, "excluded": {}, "reference_device_intervals": len(parsed.reference.device_intervals),
              "reference_usable": 0, "reference_excluded": {}}
    for res in results.values():
        totals["evaluated"] += res.evaluated
        totals["flagged"] += len(res.flagged)
        totals["insufficient_reference"] += res.insufficient
        totals["reference_usable"] += res.reference_usable
        for k, v in res.excluded.items():
            totals["excluded"][k] = totals["excluded"].get(k, 0) + v
        for k, v in res.reference_excluded.items():
            totals["reference_excluded"][k] = totals["reference_excluded"].get(k, 0) + v
        devices.append({
            "device_id": res.device.device_id, "room_id": res.device.room_id, "device_type": res.device.device_type,
            "status": res.status,
            "comparison": "conditional on room temperature/occupancy" if res.device.device_type in COMFORT_DEPENDENT_TYPES else "own fully-on reference",
            "reference": {"usable_intervals": res.reference_usable, "excluded": res.reference_excluded,
                          "baselines_by_interval_seconds": res.baselines or None},
            "evaluation": {"evaluated": res.evaluated, "flagged": len(res.flagged), "insufficient_reference": res.insufficient,
                           "insufficient_reasons": res.insufficient_reasons, "excluded": res.excluded},
        })

    statuses = {d["status"] for d in devices}
    if out["findings"]:
        status = "findings_detected"
    else:
        status = next(s for s in STATUS_ORDER[1:] if s in statuses or s == "no_comparable_observations")

    warnings = [
        {"code": "NOT_A_DIAGNOSIS", "message": "Findings are statistical excess-consumption deviations versus the device's own earlier "
                                               "comparable operation; they do not confirm a malfunction, voltage fault or efficiency loss."},
        {"code": "DRIFT_NOT_ANALYSED", "message": "Gradual deterioration (trend/drift) is not detected by this detector; it compares "
                                                  "intervals with a fixed earlier reference only."},
    ]
    dupes = parsed.reference.duplicates_deduped + parsed.evaluation.duplicates_deduped
    if dupes:
        warnings.append({"code": "DUPLICATES_DEDUPED", "message": f"{dupes} identical duplicate interval record(s) were deduplicated "
                                                                  "and did not add reference support."})
    listed = len(out["exclusions"])
    total_excluded = sum(totals["excluded"].values()) + sum(totals["reference_excluded"].values())
    return {
        "status": status,
        "findings": out["findings"],
        "devices": devices,
        "coverage": totals,
        "exclusions": out["exclusions"],
        "exclusions_listed": listed,
        "exclusions_total": total_excluded,
        "warnings": warnings,
        "detector": {
            "version": DETECTOR_VERSION, "method": "rule", "technique": "robust_median_mad", "request_format": REQUEST_FORMAT,
            "parameters": {"min_reference_support": MIN_REFERENCE_SUPPORT, "min_reference_span_hours": MIN_REFERENCE_SPAN_HOURS,
                           "mad_scale": MAD_SCALE, "threshold_k": THRESHOLD_K, "abs_floor_w": ABS_FLOOR_W, "rel_floor": REL_FLOOR,
                           "comfort_dependent_types": list(COMFORT_DEPENDENT_TYPES), "temp_band_c": TEMP_BAND_C,
                           "occupancy_band": OCCUPANCY_BAND, "fully_on_only": True, "max_exclusions_listed": MAX_EXCLUSIONS_LISTED},
            "model_used": False,
        },
        "analysis": {
            "contract_version": req.contract_version, "dataset_id": req.dataset_id, "run_id": req.run_id,
            "reference_window": req.reference.window.model_dump(), "evaluation_window": req.evaluation.window.model_dump(),
            "bounds": {"device_intervals_per_section": MAX_DEVICE_INTERVALS_PER_SECTION,
                       "room_intervals_per_section": MAX_ROOM_INTERVALS_PER_SECTION},
        },
    }
