"""POST /v1/drift orchestration: validate (shared with /v1/anomalies) → trend detection → honest status."""

from ..anomalies.constants import COMFORT_DEPENDENT_TYPES, MAX_DEVICE_INTERVALS_PER_SECTION, MAX_ROOM_INTERVALS_PER_SECTION
from ..anomalies.validate import parse_anomaly_request
from . import constants as C
from .detector import detect_trends, finding_for


def run_drift(raw: bytes) -> dict:
    parsed = parse_anomaly_request(raw, detector_version=C.DETECTOR_VERSION)
    req = parsed.request
    out = detect_trends(parsed)
    results = out["results"]

    findings, devices, other_changes = [], [], []
    for res in results.values():
        if res.classification == "sustained_upward_trend":
            findings.append(finding_for(res, req))
        elif res.classification in ("abrupt_level_change", "upward_change_not_sustained", "level_offset_without_trend"):
            other_changes.append({"device_id": res.device.device_id, "classification": res.classification,
                                  "note": "Not classified as a gradual trend.", "metrics": res.metrics, "spike_days": res.spikes})
        devices.append({
            "device_id": res.device.device_id, "room_id": res.device.room_id, "device_type": res.device.device_type,
            "status": res.status, "classification": res.classification, "reason": res.reason,
            "context": "room temperature bin + occupied state" if res.device.device_type in COMFORT_DEPENDENT_TYPES else "local hour",
            "resolution_seconds": res.resolution_seconds, "policy_ref": res.policy_ref, "reference_level_w": res.reference_level_w,
            "contexts_with_baseline": res.contexts,
            "support": {"reference_days": res.reference_days, "evaluation_days": res.evaluation_days,
                        "evaluation_span_days": res.evaluation_span_days, "reference_observations": res.reference_observations,
                        "evaluation_observations": res.evaluation_observations},
            "excluded": {"reference": res.reference_excluded, "evaluation": res.evaluation_excluded},
            "spike_days": res.spikes,
        })

    statuses = [d["status"] for d in devices]
    if findings:
        status = "findings_detected"
    elif "evaluated" in statuses:
        status = "evaluated_no_gradual_trend"
    elif "insufficient_history" in statuses:
        status = "insufficient_history"
    elif "unsupported_context" in statuses:
        status = "unsupported_context"
    else:
        status = "no_comparable_observations"

    dupes = parsed.reference.duplicates_deduped + parsed.evaluation.duplicates_deduped
    warnings = [
        {"code": "NOT_AN_EFFICIENCY_DIAGNOSIS", "message": "A sustained upward power trend under matched observed conditions does not "
                                                           "establish reduced efficiency or a fault: delivered output, outdoor conditions, "
                                                           "setpoints and workload are not observed."},
        {"code": "NOT_ADDITIVE", "message": "Do not add trend magnitudes to vacancy or excess-consumption findings; they can overlap."},
    ]
    if dupes:
        warnings.append({"code": "DUPLICATES_DEDUPED", "message": f"{dupes} identical duplicate interval record(s) were deduplicated "
                                                                  "and did not add support."})
    return {
        "status": status,
        "findings": findings,
        "other_changes": other_changes,
        "devices": devices,
        "coverage": {
            "devices": len(devices),
            "evaluated": sum(1 for s in statuses if s == "evaluated"),
            "insufficient_history": statuses.count("insufficient_history"),
            "unsupported_context": statuses.count("unsupported_context"),
            "no_comparable_observations": statuses.count("no_comparable_observations"),
            "reference_device_intervals": len(parsed.reference.device_intervals),
            "evaluation_device_intervals": len(parsed.evaluation.device_intervals),
        },
        "exclusions": out["exclusions"],
        "warnings": warnings,
        "detector": {
            "version": C.DETECTOR_VERSION, "method": "rule", "technique": "theil_sen_context_normalised_daily",
            "request_format": C.REQUEST_FORMAT, "model_used": False,
            "parameters": {k.lower(): getattr(C, k) for k in dir(C) if k.isupper() and k not in ("DETECTOR_VERSION", "REQUEST_FORMAT",
                                                                                                 "FINDING_TYPE", "FINDING_TITLE")},
        },
        "analysis": {
            "contract_version": req.contract_version, "dataset_id": req.dataset_id, "run_id": req.run_id,
            "reference_window": req.reference.window.model_dump(), "evaluation_window": req.evaluation.window.model_dump(),
            "bounds": {"device_intervals_per_section": MAX_DEVICE_INTERVALS_PER_SECTION,
                       "room_intervals_per_section": MAX_ROOM_INTERVALS_PER_SECTION},
        },
    }
