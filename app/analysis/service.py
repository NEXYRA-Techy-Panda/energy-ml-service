"""POST /v1/analyze orchestration: validate → deterministic rule → response payload."""

from .rules import RULE_VERSION, run_rule
from .validate import MAX_DEVICE_INTERVALS, MAX_ROOM_INTERVALS, parse_request

NOT_PERFORMED = (
    "Only the deterministic vacant-beyond-grace rule is implemented. No drift detection, spike detection, "
    "anomaly model or forecast was performed, and no trained model was used."
)


def analyze(raw: bytes) -> dict:
    parsed = parse_request(raw)
    req = parsed.request
    result = run_rule(req, parsed.room_intervals, parsed.device_intervals)
    warnings = list(result.warnings)
    if parsed.duplicates_deduped:
        warnings.append({"code": "DUPLICATES_DEDUPED",
                         "message": f"{parsed.duplicates_deduped} identical duplicate interval record(s) were deduplicated."})
    warnings.append({"code": "ANALYSES_NOT_PERFORMED", "message": NOT_PERFORMED})
    return {
        "findings": result.findings,
        "warnings": warnings,
        "analysis": {
            "contract_version": req.contract_version,
            "dataset_id": req.dataset_id,
            "run_id": req.run_id,
            "window": {"start_utc": req.window.start_utc, "end_utc": req.window.end_utc},
            "method": "rule",
            "rules": [RULE_VERSION],
            "model_used": False,
            "records": {
                "room_intervals": len(parsed.room_intervals),
                "device_intervals": len(parsed.device_intervals),
                "duplicates_deduped": parsed.duplicates_deduped,
                "bounds": {"room_intervals": MAX_ROOM_INTERVALS, "device_intervals": MAX_DEVICE_INTERVALS},
            },
            "excluded_devices": result.excluded,
        },
    }
