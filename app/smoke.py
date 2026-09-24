"""Release smoke check for energy-ml-service (P029-PREP).

    python -m app.smoke                                    # in-process (default): the real FastAPI app, no listener
    python -m app.smoke --url http://127.0.0.1:19003       # explicit loopback HTTP target
    python -m app.smoke --json smoke-report.json           # also write a machine-readable report

Checks the supported release behaviour: health/model info, /v1/analyze
(vacancy rule, contract reference fixture), /v1/forecast (statistical
baseline + insufficient history), /v1/anomalies (excess-consumption deviation
+ insufficient reference), /v1/drift (sustained upward trend + insufficient
history) and representative validation errors. All fixtures are small and
SYNTHETIC (or the contract reference fixture); no labels are sent.

Exit status: 0 = all checks passed; 1 = at least one application check
failed; 2 = runner/target error (bad arguments, target unreachable, timeout).
Skipped checks never count as passed. Only the standard library and the
service's own runtime dependencies are used (no httpx, no test framework).
Reports contain summaries only — never full payloads or environment values.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
EXPECTED_CONTRACT_VERSION = "1.0.1"
TOOL_VERSION = "p029-smoke-v1"


# ------------------------------------------------------------------ transports


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


class TransportError(Exception):
    """The target could not be reached or did not answer in time (not an application failure)."""


class InProcessTransport:
    """Calls the real ASGI application directly (no socket, no listener)."""

    mode = "in-process"

    def __init__(self, timeout: float = 30.0):
        from .main import app  # imported lazily so HTTP mode never loads the app

        self.app = app
        self.timeout = timeout
        self.target = "in-process app.main:app"

    def request(self, method: str, path: str, body: bytes | None = None) -> Response:
        return asyncio.run(self._call(method, path, body or b""))

    async def _call(self, method: str, path: str, body: bytes) -> Response:
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
            "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "headers": [(b"host", b"in-process"), (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            "client": ("127.0.0.1", 0), "server": ("in-process", 80),
        }
        done = asyncio.Event()
        delivered = False
        messages: list[dict] = []

        async def receive() -> dict:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                done.set()

        try:
            await asyncio.wait_for(self.app(scope, receive, send), self.timeout)
        except asyncio.TimeoutError:
            raise TransportError(f"in-process request {method} {path} exceeded {self.timeout} s") from None
        start = next((m for m in messages if m["type"] == "http.response.start"), None)
        if start is None:
            raise TransportError(f"in-process request {method} {path} produced no response")
        headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
        return Response(start["status"], headers, b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body"))


class HttpTransport:
    """Explicit loopback HTTP target with a bounded timeout; no retries, no fallback."""

    mode = "http"

    def __init__(self, base_url: str, timeout: float = 10.0):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS or parsed.path not in ("", "/"):
            raise ValueError(f"--url must be a loopback origin such as http://127.0.0.1:19003 (got {base_url!r}); "
                             "the Python service is private and is never checked through a public URL")
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.target = self.base

    def request(self, method: str, path: str, body: bytes | None = None) -> Response:
        req = urllib.request.Request(self.base + path, data=body, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                return Response(res.status, {k.lower(): v for k, v in res.headers.items()}, res.read())
        except urllib.error.HTTPError as exc:  # an HTTP answer (4xx/5xx) is an application response, not a transport error
            return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise TransportError(f"{method} {self.base}{path} failed: {type(reason).__name__}: {reason}") from None


# ------------------------------------------------------------------ checks


class CheckFailed(Exception):
    def __init__(self, message: str, expected: Any = None, observed: Any = None):
        super().__init__(message)
        self.expected, self.observed = expected, observed


def expect(condition: bool, message: str, expected: Any = None, observed: Any = None) -> None:
    if not condition:
        raise CheckFailed(message, expected, observed)


def call_json(client, method: str, path: str, payload: Any | None = None) -> tuple[int, dict, dict]:
    body = None if payload is None else (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    res = client.request(method, path, body)
    try:
        doc = res.json()
    except ValueError:
        raise CheckFailed(f"{path} did not return JSON", "JSON body", f"HTTP {res.status}, {len(res.body)} bytes") from None
    return res.status, doc, res.headers


def ok_data(client, method: str, path: str, payload: Any | None = None) -> dict:
    status, doc, headers = call_json(client, method, path, payload)
    expect(status == 200, f"{path} status", 200, {"status": status, "error": doc.get("error")})
    expect(isinstance(doc.get("data"), dict) and isinstance(doc.get("meta"), dict) and doc["meta"].get("request_id"),
           f"{path} success envelope", "{data, meta:{request_id}}", sorted(doc))
    expect(headers.get("x-request-id") == doc["meta"]["request_id"], f"{path} X-Request-Id header matches meta.request_id")
    return doc["data"]


def error_body(client, path: str, payload: Any, status_expected: int) -> dict:
    status, doc, _ = call_json(client, "POST", path, payload)
    expect(status == status_expected, f"{path} status", status_expected, {"status": status, "error": doc.get("error")})
    expect(isinstance(doc.get("error"), dict) and doc["error"].get("code") and doc["error"].get("message"),
           f"{path} error envelope", "{error:{code, message}}", doc)
    return doc["error"]


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


# Fixtures (small; SYNTHETIC or the contract reference fixture). No evaluation labels are ever sent.


def analyze_fixture() -> dict:
    ref = json.loads((REPO_ROOT / "contracts" / "v1" / "fixtures" / "reference.json").read_text(encoding="utf-8"))
    return {"contract_version": "1.0.1", "dataset_id": "smoke-fixture", "run_id": ref["run"]["run_id"],
            "window": {"start_utc": ref["export"]["export_start_utc"], "end_utc": ref["export"]["export_end_utc"]},
            "rooms": ref["rooms"], "devices": ref["devices"], "policies": ref["policies"],
            "room_intervals": ref["room_intervals"], "device_intervals": ref["device_intervals"],
            "options": {"tariff_inr_per_kwh": 10.0}}


def forecast_fixture(days: int = 7) -> dict:
    from .forecast.synthetic import synthetic_history

    ist = ZoneInfo("Asia/Kolkata")
    origin = datetime(2027, 1, 4, tzinfo=ist).astimezone(timezone.utc)  # Monday 00:00 local
    hist = synthetic_history(datetime(2027, 1, 4, tzinfo=ist) - timedelta(days=days), days, seed=4242)
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return {"contract_version": "1.0.1", "dataset_id": "smoke-synthetic", "origin_utc": fmt(origin), "horizon": "next_24h",
            "history_hourly_kwh": [{"start_utc": fmt(t), "energy_kwh": round(v, 4)} for t, v in sorted(hist.items())],
            "calendar": {"timezone": "Asia/Kolkata", "working_days_iso": [1, 2, 3, 4, 5], "open_local": "09:00", "close_local": "18:00"}}


def _light_only() -> tuple[list, list]:
    from .anomalies.synthetic import DEVICES, POLICIES

    return [d for d in DEVICES if d["device_id"] == "light-a"], [p for p in POLICIES if p["policy_id"] in ("pol-hours", "pol-light-a")]


def anomalies_fixture(reference_intervals: int = 24) -> dict:
    from .anomalies.synthetic import build_request

    devices, policies = _light_only()

    def power(section: str, dev: str, i: int):
        if section == "reference":
            return (round(72.0 * (1 + 0.004 * ((i % 5) - 2)), 3), 1.0)
        return [(72.2, 1.0), (104.5, 1.0), (105.1, 1.0), (36.0, 0.5)][i]

    body = build_request(reference_intervals, 4, power, room=lambda s, r, i: (25.0, 2.0) if r == "room-a" else None, devices=devices)
    body["policies"] = policies
    return body


def drift_fixture(eval_days: int = 14) -> dict:
    from .drift.synthetic import build_drift_request

    devices, _ = _light_only()
    policies = [p for p in _light_only()[1] if p["policy_id"] == "pol-light-a"]
    jitter = lambda day, h: 1 + 0.01 * (((day * 3 + h) % 5) - 2)  # noqa: E731

    def power(section: str, dev: str, day: int, hour: int):
        factor = 1.0 if section == "reference" else 1 + 0.30 * day / 13
        return (round(72.0 * factor * jitter(day, hour), 3), 1.0)

    return build_drift_request(7, eval_days, power, room=lambda s, r, d, h: (25.0, 4.0) if r == "room-a" else None,
                               hours=lambda s, d, day: (10, 11, 12), devices=devices, policies=policies)


def check_health(client, ctx: dict) -> dict:
    data = ok_data(client, "GET", "/health")
    expect(data.get("status") == "ok", "health status", "ok", data.get("status"))
    expect(data.get("model_available") is False, "model_available is false (no trained model deployed)", False, data.get("model_available"))
    return {"status": data["status"], "model_available": data["model_available"]}


def check_model_info(client, ctx: dict) -> dict:
    from .forecast.constants import BASELINE_VERSION

    data = ok_data(client, "GET", "/v1/model/info")
    expect(data.get("contract_version") == EXPECTED_CONTRACT_VERSION, "contract version", EXPECTED_CONTRACT_VERSION, data.get("contract_version"))
    expect(data.get("model_available") is False and data.get("model_version") is None, "no trained model advertised",
           {"model_available": False, "model_version": None}, {k: data.get(k) for k in ("model_available", "model_version")})
    expect(data.get("baseline_version") == BASELINE_VERSION, "baseline identity matches the checked-out implementation",
           BASELINE_VERSION, data.get("baseline_version"))
    ctx["versions"].update(contract_version=data["contract_version"], model_available=data["model_available"],
                           model_version=data["model_version"], baseline_version=data["baseline_version"])
    return {k: data[k] for k in ("contract_version", "model_available", "model_version", "baseline_version")}


def check_analyze(client, ctx: dict) -> dict:
    data = ok_data(client, "POST", "/v1/analyze", analyze_fixture())
    findings = data["findings"]
    expect(len(findings) == 1, "exactly one vacancy finding", 1, len(findings))
    f = findings[0]
    expect(f["device_id"] == "light-a" and f["finding_type"] == "vacant_but_on" and f["method"] == "rule",
           "light-a vacant_but_on rule finding", "light-a/vacant_but_on/rule", [f["device_id"], f["finding_type"], f["method"]])
    expect(close(f.get("avoidable_energy_kwh", -1), 0.01), "avoidable energy", 0.01, f.get("avoidable_energy_kwh"))
    expect(close(f.get("avoidable_cost_inr", -1), 0.10), "avoidable cost at INR 10/kWh", 0.10, f.get("avoidable_cost_inr"))
    excluded = [e["device_id"] for e in data["analysis"]["excluded_devices"]]
    expect("fridge-b" in excluded and all(x["device_id"] != "fridge-b" for x in findings), "refrigerator excluded", "fridge-b excluded", excluded)
    ctx["versions"]["analyze_rules"] = data["analysis"]["rules"]
    return {"findings": 1, "avoidable_energy_kwh": f["avoidable_energy_kwh"], "avoidable_cost_inr": f["avoidable_cost_inr"], "excluded": excluded}


def check_forecast(client, ctx: dict) -> dict:
    body = forecast_fixture()
    data = ok_data(client, "POST", "/v1/forecast", body)
    pts = data["points"]
    expect(len(pts) == 24, "next_24h returns 24 hourly points", 24, len(pts))
    starts = [datetime.strptime(p["start_utc"], "%Y-%m-%dT%H:%M:%SZ") for p in pts]
    expect(all((b - a).total_seconds() == 3600 for a, b in zip(starts, starts[1:])), "points ordered and hourly")
    expect(pts[0]["start_utc"] == body["origin_utc"] == data["horizon_start_utc"], "horizon starts at the origin", body["origin_utc"], pts[0]["start_utc"])
    total = sum(p["energy_kwh"] for p in pts)
    expect(close(total, data["total_energy_kwh"]), "total reconciles with points", total, data["total_energy_kwh"])
    expect(data["method"] == "statistical_baseline" and data["model_version"] is None and data["uncertainty"] == "unavailable",
           "statistical-baseline labelling", "statistical_baseline/null/unavailable", [data["method"], data["model_version"], data["uncertainty"]])
    expect(data["baseline_version"] == ctx["versions"].get("baseline_version", data["baseline_version"]), "baseline version consistent with model info")
    expect(bool(data.get("limitations")), "limitations present")
    ctx["versions"]["forecast_baseline_version"] = data["baseline_version"]
    return {"points": len(pts), "total_energy_kwh": round(data["total_energy_kwh"], 4), "basis_counts": data["basis_counts"]}


def check_forecast_insufficient(client, ctx: dict) -> dict:
    body = forecast_fixture()
    body["history_hourly_kwh"] = body["history_hourly_kwh"][-72:]
    err = error_body(client, "/v1/forecast", body, 422)
    expect(err["code"] == "INSUFFICIENT_DATA", "insufficient history code", "INSUFFICIENT_DATA", err["code"])
    return {"status": 422, "code": err["code"]}


def check_anomalies(client, ctx: dict) -> dict:
    data = ok_data(client, "POST", "/v1/anomalies", anomalies_fixture())
    expect(data["status"] == "findings_detected", "anomaly status", "findings_detected", data["status"])
    expect(len(data["findings"]) == 1, "exactly one deviation finding", 1, len(data["findings"]))
    f = data["findings"][0]
    expect(f["device_id"] == "light-a" and f["finding_type"] == "excess_consumption_deviation",
           "light-a excess-consumption deviation", "light-a/excess_consumption_deviation", [f["device_id"], f["finding_type"]])
    expect(f["observed"]["value"] > f["threshold_w"] > f["expected"]["value"], "observed above threshold above baseline",
           "observed > threshold > expected", [f["observed"]["value"], f["threshold_w"], f["expected"]["value"]])
    cov = data["coverage"]
    expect(cov["evaluated"] == 3 and cov["excluded"] == {"mixed_duty": 1} and data["exclusions"], "coverage and exclusions reported",
           {"evaluated": 3, "excluded": {"mixed_duty": 1}}, {"evaluated": cov["evaluated"], "excluded": cov["excluded"]})
    expect("avoidable_energy_kwh" not in f and "NOT_A_DIAGNOSIS" in {w["code"] for w in data["warnings"]}, "deviation, not savings or diagnosis")
    ctx["versions"]["anomalies_detector"] = data["detector"]["version"]
    return {"observed_w": round(f["observed"]["value"], 3), "expected_w": round(f["expected"]["value"], 3), "threshold_w": round(f["threshold_w"], 3),
            "evaluated": cov["evaluated"], "excluded": cov["excluded"]}


def check_anomalies_insufficient(client, ctx: dict) -> dict:
    data = ok_data(client, "POST", "/v1/anomalies", anomalies_fixture(reference_intervals=6))
    expect(data["status"] == "insufficient_reference", "insufficient reference is not evaluated-no-deviation",
           "insufficient_reference", data["status"])
    expect(data["findings"] == [] and data["coverage"]["evaluated"] == 0, "nothing evaluated, no findings",
           {"findings": 0, "evaluated": 0}, {"findings": len(data["findings"]), "evaluated": data["coverage"]["evaluated"]})
    return {"status": data["status"], "insufficient_reference": data["coverage"]["insufficient_reference"]}


def check_drift(client, ctx: dict) -> dict:
    data = ok_data(client, "POST", "/v1/drift", drift_fixture())
    expect(data["status"] == "findings_detected" and len(data["findings"]) == 1, "one sustained trend finding", 1, len(data["findings"]))
    f = data["findings"][0]
    rel = f["trend"]["relative_change_over_period"]
    expect(f["finding_type"] == "sustained_upward_power_trend" and rel >= 0.10, "material sustained upward trend", ">= 0.10", rel)
    keys = set(f) | set(f["trend"])
    expect(not keys & {"avoidable_energy_kwh", "avoidable_cost_inr", "savings", "roi"}, "no savings/ROI fields", None, sorted(keys))
    expect("NOT_AN_EFFICIENCY_DIAGNOSIS" in {w["code"] for w in data["warnings"]}, "efficiency-diagnosis disclaimer present")
    ctx["versions"]["drift_detector"] = data["detector"]["version"]
    return {"relative_change_over_period": round(rel, 4), "watts_per_day": round(f["trend"]["watts_per_day"], 4),
            "evaluation_days": f["support"]["evaluation_days"]}


def check_drift_insufficient(client, ctx: dict) -> dict:
    data = ok_data(client, "POST", "/v1/drift", drift_fixture(eval_days=6))
    expect(data["status"] == "insufficient_history" and data["findings"] == [], "short evaluation is insufficient history",
           "insufficient_history", data["status"])
    return {"status": data["status"], "reason": data["devices"][0]["reason"]}


def check_fault_label_rejected(client, ctx: dict) -> dict:
    body = analyze_fixture()
    body["policies"][1]["rules"]["fault_active"] = True  # nested injected-fault field
    err = error_body(client, "/v1/analyze", body, 400)
    expect(err["code"] == "VALIDATION_ERROR" and err.get("field") == "policies[1].rules.fault_active", "nested fault label rejected",
           "VALIDATION_ERROR at policies[1].rules.fault_active", [err["code"], err.get("field")])
    return {"status": 400, "field": err["field"]}


def check_record_limit_rejected(client, ctx: dict) -> dict:
    body = anomalies_fixture()
    body["evaluation"]["device_intervals"] = [copy.deepcopy(body["evaluation"]["device_intervals"][0])] * 2001
    err = error_body(client, "/v1/anomalies", body, 413)
    expect(err["code"] == "REQUEST_TOO_LARGE" and err.get("field") == "evaluation.device_intervals", "per-section record limit",
           "REQUEST_TOO_LARGE at evaluation.device_intervals", [err["code"], err.get("field")])
    return {"status": 413, "field": err["field"]}


CHECKS: list[tuple[str, str, Callable]] = [
    ("health", "GET /health", check_health),
    ("model_info", "GET /v1/model/info", check_model_info),
    ("analyze_vacancy_reference_fixture", "POST /v1/analyze", check_analyze),
    ("forecast_statistical_baseline", "POST /v1/forecast", check_forecast),
    ("forecast_insufficient_history", "POST /v1/forecast", check_forecast_insufficient),
    ("anomalies_excess_deviation", "POST /v1/anomalies", check_anomalies),
    ("anomalies_insufficient_reference", "POST /v1/anomalies", check_anomalies_insufficient),
    ("drift_sustained_trend", "POST /v1/drift", check_drift),
    ("drift_insufficient_history", "POST /v1/drift", check_drift_insufficient),
    ("validation_nested_fault_label", "POST /v1/analyze", check_fault_label_rejected),
    ("validation_record_limit", "POST /v1/anomalies", check_record_limit_rejected),
]


# ------------------------------------------------------------------ runner


@dataclass
class CheckResult:
    name: str
    endpoint: str
    outcome: str  # pass | fail | error | skip
    seconds: float
    summary: dict = field(default_factory=dict)
    message: str | None = None
    expected: Any = None
    observed: Any = None


def _safe(value: Any, limit: int = 300) -> Any:
    text = json.dumps(value, default=str)
    return value if len(text) <= limit else text[:limit] + "..."


def run_checks(client, checks: list[tuple[str, str, Callable]] | None = None) -> dict:
    ctx: dict = {"versions": {}}
    results: list[CheckResult] = []
    unreachable = None
    for name, endpoint, fn in checks or CHECKS:
        if unreachable:
            results.append(CheckResult(name, endpoint, "skip", 0.0, message=f"not run: target error in an earlier check ({unreachable})"))
            continue
        t0 = time.perf_counter()
        try:
            summary = fn(client, ctx)
            results.append(CheckResult(name, endpoint, "pass", time.perf_counter() - t0, summary))
        except CheckFailed as exc:
            results.append(CheckResult(name, endpoint, "fail", time.perf_counter() - t0, message=str(exc),
                                       expected=_safe(exc.expected), observed=_safe(exc.observed)))
        except TransportError as exc:
            unreachable = name
            results.append(CheckResult(name, endpoint, "error", time.perf_counter() - t0, message=str(exc)))
        except Exception as exc:  # unexpected response shape etc. — an application-level failure, reported safely
            results.append(CheckResult(name, endpoint, "fail", time.perf_counter() - t0, message=f"{type(exc).__name__}: {exc}"))
    counts = {k: sum(1 for r in results if r.outcome == k) for k in ("pass", "fail", "error", "skip")}
    exit_code = 2 if counts["error"] else (1 if counts["fail"] else 0)
    return {"results": results, "counts": counts, "versions": ctx["versions"], "exit_code": exit_code}


def checkout_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def build_report(client, outcome: dict) -> dict:
    return {
        "tool": TOOL_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": client.mode,
        "target": client.target,
        "runner_checkout_commit": checkout_commit(),
        "note": "runner_checkout_commit is the checkout running this tool; in HTTP mode confirm the SERVICE's deployed commit separately. "
                "Python checks alone do not verify Node integration, browsers or deployment.",
        "versions_returned": outcome["versions"],
        "counts": outcome["counts"],
        "exit_code": outcome["exit_code"],
        "results": [asdict(r) for r in outcome["results"]],
    }


def render(report: dict) -> str:
    lines = [f"energy-ml-service smoke check ({report['tool']}) - mode: {report['mode']} - target: {report['target']}",
             f"runner checkout commit: {report['runner_checkout_commit'] or 'unknown'}"]
    for r in report["results"]:
        line = f"  {r['outcome'].upper():5} {r['name']:<36} {r['endpoint']:<22} {r['seconds'] * 1000:7.1f} ms"
        if r["outcome"] == "pass" and r["summary"]:
            line += f"  {json.dumps(r['summary'], ensure_ascii=False)}"
        lines.append(line)
        if r["outcome"] in ("fail", "error", "skip"):
            lines.append(f"        {r['message']}")
            if r["outcome"] == "fail" and (r["expected"] is not None or r["observed"] is not None):
                lines.append(f"        expected: {json.dumps(r['expected'], ensure_ascii=False, default=str)}")
                lines.append(f"        observed: {json.dumps(r['observed'], ensure_ascii=False, default=str)}")
    c = report["counts"]
    lines.append(f"versions returned: {json.dumps(report['versions_returned'], ensure_ascii=False)}")
    lines.append(f"RESULT: {c['pass']} passed, {c['fail']} failed, {c['error']} errors, {c['skip']} skipped - exit {report['exit_code']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.smoke", description="energy-ml-service release smoke check")
    ap.add_argument("--url", help="explicit loopback HTTP target, e.g. http://127.0.0.1:19003 (default: in-process)")
    ap.add_argument("--timeout", type=float, default=10.0, help="per-request timeout in seconds (default 10)")
    ap.add_argument("--json", dest="json_path", help="also write a machine-readable report to this path")
    args = ap.parse_args(argv)
    try:
        client = HttpTransport(args.url, args.timeout) if args.url else InProcessTransport(max(args.timeout, 30.0))
    except ValueError as exc:
        print(f"smoke: {exc}", file=sys.stderr)
        return 2
    report = build_report(client, run_checks(client))
    print(render(report).encode("ascii", "backslashreplace").decode("ascii"))  # console-safe on any code page
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
