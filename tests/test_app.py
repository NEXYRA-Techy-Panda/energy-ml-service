import re

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import app

client = TestClient(app)
UUID = re.compile(r"^[0-9a-f-]{36}$")


def test_health_reports_ok_without_a_model():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["data"] == {"status": "ok", "model_available": False}
    assert UUID.match(body["meta"]["request_id"])
    assert res.headers["x-request-id"] == body["meta"]["request_id"]


def test_model_info_is_uninitialised_not_fabricated():
    res = client.get("/v1/model/info")
    assert res.status_code == 200
    assert res.json()["data"] == {
        "model_available": False,
        "model_version": None,
        "baseline_version": "hourly-profile-median-v1",  # statistical forecast baseline, not a trained model
        "contract_version": "1.0.1",
    }


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/api/v1/health", "/v1/train"])
def test_unimplemented_routes_return_not_found_envelope(path):
    res = client.post(path) if path.startswith("/v1/") else client.get(path)
    assert res.status_code == 404
    assert res.json() == {"error": {"code": "NOT_FOUND", "message": f"No route for {res.request.method} {path}"}}


def test_settings_use_fixed_port_and_ignore_port_environment(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    settings = load_settings()
    assert (settings.host, settings.port) == ("127.0.0.1", 19003)
    monkeypatch.setenv("PORT", "eighty")
    assert load_settings().port == 19003
