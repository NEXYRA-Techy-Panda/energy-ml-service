"""P029-PREP release smoke runner: outcomes, exit codes, target safety and report hygiene.

No listener is started: in-process mode drives the real ASGI app directly, and
HTTP-mode failure handling is exercised against a loopback port with nothing
listening (connection refused) or with fake transports.
"""

import json
import socket

import pytest

from app import smoke


def free_closed_port() -> int:
    """A loopback port that nothing listens on (bound, released, never listened)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_in_process_all_checks_pass_with_exit_0(tmp_path, capsys):
    out = tmp_path / "report.json"
    assert smoke.main(["--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["mode"] == "in-process"
    assert report["counts"] == {"pass": len(smoke.CHECKS), "fail": 0, "error": 0, "skip": 0}
    assert [r["name"] for r in report["results"]] == [name for name, _, _ in smoke.CHECKS]
    v = report["versions_returned"]
    assert v["contract_version"] == "1.0.1" and v["model_available"] is False and v["model_version"] is None
    assert v["baseline_version"] == "hourly-profile-median-v1"
    assert v["anomalies_detector"] == "excess-power-mad-v1" and v["drift_detector"] == "gradual-power-trend-v1"
    assert "RESULT: 11 passed, 0 failed, 0 errors, 0 skipped - exit 0" in capsys.readouterr().out


def test_report_contains_summaries_not_payloads(tmp_path):
    out = tmp_path / "report.json"
    smoke.main(["--json", str(out)])
    text = out.read_text(encoding="utf-8")
    assert len(text) < 20_000
    # interval/history record keys would mean a request or response payload leaked into the report
    for record_key in ('"avg_power_w"', '"interval_start_utc"', '"start_utc"', '"energy_kwh"', '"occupancy_avg"', '"room_id"'):
        assert record_key not in text


class Wrong:
    """Wraps the real app but falsifies model info, as a regressed deployment would."""

    mode, target = "fake", "fake"

    def __init__(self):
        self.inner = smoke.InProcessTransport()

    def request(self, method, path, body=None):
        res = self.inner.request(method, path, body)
        if path == "/v1/model/info":
            doc = res.json()
            doc["data"]["contract_version"] = "0.9.0"
            res = smoke.Response(res.status, res.headers, json.dumps(doc).encode())
        return res


def test_wrong_response_is_a_failure_with_exit_1_and_other_checks_still_run():
    outcome = smoke.run_checks(Wrong())
    by = {r.name: r for r in outcome["results"]}
    assert by["model_info"].outcome == "fail"
    assert by["model_info"].expected == "1.0.1" and by["model_info"].observed == "0.9.0"
    assert outcome["counts"] == {"pass": len(smoke.CHECKS) - 1, "fail": 1, "error": 0, "skip": 0}
    assert outcome["exit_code"] == 1


def test_unreachable_target_is_an_error_not_a_failure_and_rest_are_skipped_not_passed(capsys):
    code = smoke.main(["--url", f"http://127.0.0.1:{free_closed_port()}", "--timeout", "2"])
    out = capsys.readouterr().out
    assert code == 2
    assert "ERROR health" in out
    assert f"RESULT: 0 passed, 0 failed, 1 errors, {len(smoke.CHECKS) - 1} skipped - exit 2" in out


def test_http_error_status_is_an_application_response_not_a_transport_error():
    class Http500:
        mode, target = "fake", "fake"

        def request(self, method, path, body=None):
            return smoke.Response(500, {}, b'{"error":{"code":"INTERNAL","message":"boom"}}')

    outcome = smoke.run_checks(Http500())
    assert outcome["counts"]["error"] == 0 and outcome["counts"]["fail"] == len(smoke.CHECKS)
    assert outcome["exit_code"] == 1


@pytest.mark.parametrize("url", [
    "https://git-pipeline.metatronhost.in/auditor",  # public: never a smoke target
    "http://example.com:19003",
    "http://10.0.0.5:19003",
    "https://127.0.0.1:19003",
    "http://127.0.0.1:19003/api",
])
def test_non_loopback_or_non_origin_urls_are_rejected(url, capsys):
    assert smoke.main(["--url", url]) == 2
    assert "must be a loopback origin" in capsys.readouterr().err


@pytest.mark.parametrize("url", ["http://127.0.0.1:19003", "http://localhost:19003/", "http://[::1]:19003"])
def test_loopback_origins_are_accepted_without_connecting(url):
    assert smoke.HttpTransport(url, 1.0).target == url.rstrip("/")


def test_default_mode_is_in_process_never_http(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("default mode must not open network connections")

    monkeypatch.setattr(smoke.urllib.request, "urlopen", refuse)
    assert smoke.main([]) == 0
