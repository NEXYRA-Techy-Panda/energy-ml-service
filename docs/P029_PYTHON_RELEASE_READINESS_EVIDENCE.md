# P029-PREP — Python release verification evidence

Developer Mohan | Agent M-C — Claude Code | P029-PREP | review **pending**.
Supporting Mohan release-readiness batch 28 / approximately 29.
Date: 2026-09-25 (IST). Base commit: `a0a86cc` (deployed Python baseline, port fixed at 19003).

## 1. What was added

| Item | Purpose |
|---|---|
| `app/smoke.py` (`python -m app.smoke`) | One repeatable smoke check of the supported Python capabilities |
| `tests/test_smoke.py` (14 tests) | Runner outcomes, exit codes, target safety, report hygiene |
| `.gitattributes` | `contracts/v1/** text eol=lf`, `scripts/verify-contract.mjs text eol=lf` |

No API, model, detector, port, PM2, Nginx, webhook or contract change. The
runner uses only the standard library plus the service's own runtime
dependencies. It does **not** need `httpx`/`pytest`, so it runs in a
runtime-only environment (`requirements.txt`).

## 2. Modes and safety

- **In-process (default)**: calls the real ASGI application `app.main:app`
  directly (no socket, no listener, no port). This is the mode used during
  P029-PREP; port 19003 was not bound.
- **HTTP (explicit)**: `--url` is required and must be a loopback origin
  (`http://127.0.0.1:…`, `http://localhost:…`, `http://[::1]:…`). Public or
  non-loopback URLs (including `https://git-pipeline.metatronhost.in/...`)
  are refused with exit 2. There is no default target, no fallback from HTTP
  to in-process, no retries. Per-request timeout `--timeout` (default 10 s).
- **Outcomes** are kept separate: `pass`, `fail` (the service answered
  incorrectly — includes HTTP 4xx/5xx where success was expected), `error`
  (target unreachable/timeout — not an application failure), `skip` (not run
  because of an earlier target error — never counted as passed).
- **Exit status**: 0 all passed; 1 any application failure; 2 target/runner
  error (unreachable, timeout, bad `--url`).
- **Report**: human-readable on stdout (ASCII-safe for any console code
  page); `--json FILE` adds a machine report with per-check summaries,
  expected/observed on failure (truncated), returned versions, counts and the
  runner checkout commit. No request/response payloads, tokens or environment
  values are written (asserted by a test).

## 3. Checks (all fixtures small; SYNTHETIC or the contract reference fixture; no labels sent)

| Check | Endpoint | Asserts |
|---|---|---|
| health | GET /health | envelope + X-Request-Id; `status ok`; `model_available false` |
| model_info | GET /v1/model/info | contract `1.0.1`; `model_available false`, `model_version null`; baseline `hourly-profile-median-v1` |
| analyze_vacancy_reference_fixture | POST /v1/analyze | contract reference fixture → 1 finding (light-a, vacant_but_on, rule); 0.01 kWh; ₹0.10 at ₹10/kWh; fridge-b excluded |
| forecast_statistical_baseline | POST /v1/forecast | 168 h synthetic history → 24 ordered hourly points from origin; total reconciles; `statistical_baseline`, model_version null, uncertainty unavailable; limitations present |
| forecast_insufficient_history | POST /v1/forecast | 72 h → 422 `INSUFFICIENT_DATA` |
| anomalies_excess_deviation | POST /v1/anomalies | 1 light-a excess_consumption_deviation, observed > threshold > expected; coverage evaluated 3, excluded mixed_duty 1; no savings; NOT_A_DIAGNOSIS warning |
| anomalies_insufficient_reference | POST /v1/anomalies | 6 reference intervals → `insufficient_reference`, 0 evaluated (not "evaluated, no deviation") |
| drift_sustained_trend | POST /v1/drift | 1 sustained_upward_power_trend ≥ 10 %; no savings/ROI fields; NOT_AN_EFFICIENCY_DIAGNOSIS warning |
| drift_insufficient_history | POST /v1/drift | 6 evaluation days → `insufficient_history`, no findings |
| validation_nested_fault_label | POST /v1/analyze | `policies[1].rules.fault_active` → 400 VALIDATION_ERROR at that field |
| validation_record_limit | POST /v1/anomalies | 2001 evaluation device intervals → 413 REQUEST_TOO_LARGE at `evaluation.device_intervals` |

## 4. Commands

Windows (local verification; the repo's `.venv`, no Activate script):

```powershell
.venv\Scripts\python.exe -m app.smoke                                 # in-process (default)
.venv\Scripts\python.exe -m app.smoke --json smoke-report.json        # plus machine report
.venv\Scripts\python.exe -m app.smoke --url http://127.0.0.1:19003    # only against a service you know is running there
```

VPS (existing uv-managed environment — **not executed in P029-PREP**). The
repository has no `uv.lock` and no dependencies in `pyproject.toml`, so a
plain `uv run` may try to create or sync an environment and must not be used
on the production service directory. Use the interpreter the running service
already uses, from the service's working directory:

```sh
pm2 describe nexyra-energy-ml        # read-only: shows the interpreter / exec path and cwd
<that-interpreter> -m app.smoke                                     # in-process
<that-interpreter> -m app.smoke --url http://127.0.0.1:19003 --json /tmp/p029-smoke.json
```

This repository defines no uv command. If the VPS runbook already has a uv
command that runs Python in the service's existing environment, append
`-m app.smoke …` to that same command; do not introduce a new uv invocation,
sync, reinstall or replace the environment. The smoke check never restarts or
reconfigures the service.

## 5. Actual results (Windows, Python 3.13.15, in-process, checkout `a0a86cc` + P029 working tree)

```
PASS  health                              {"status": "ok", "model_available": false}
PASS  model_info                          {"contract_version": "1.0.1", "model_available": false, "model_version": null, "baseline_version": "hourly-profile-median-v1"}
PASS  analyze_vacancy_reference_fixture   {"findings": 1, "avoidable_energy_kwh": 0.01, "avoidable_cost_inr": 0.1, "excluded": ["fridge-b"]}
PASS  forecast_statistical_baseline       {"points": 24, "total_energy_kwh": 54.6749, "basis_counts": {"weekday_hour": 0, "day_class_hour": 24, "hour_of_day": 0}}
PASS  forecast_insufficient_history       {"status": 422, "code": "INSUFFICIENT_DATA"}
PASS  anomalies_excess_deviation          {"observed_w": 104.8, "expected_w": 72.0, "threshold_w": 82.0, "evaluated": 3, "excluded": {"mixed_duty": 1}}
PASS  anomalies_insufficient_reference    {"status": "insufficient_reference", "insufficient_reference": 3}
PASS  drift_sustained_trend               {"relative_change_over_period": 0.297, "watts_per_day": 1.645, "evaluation_days": 14}
PASS  drift_insufficient_history          {"status": "insufficient_history", "reason": "evaluation has 6 supported days over 6 days (coverage 1.00); needs 10 over 14 days with coverage >= 0.5"}
PASS  validation_nested_fault_label       {"status": 400, "field": "policies[1].rules.fault_active"}
PASS  validation_record_limit             {"status": 413, "field": "evaluation.device_intervals"}
versions returned: contract 1.0.1, model_available false, model_version null, baseline hourly-profile-median-v1,
  analyze rules [vacant-beyond-grace-v1], anomalies excess-power-mad-v1, drift gradual-power-trend-v1
RESULT: 11 passed, 0 failed, 0 errors, 0 skipped - exit 0
```

`model_available=false` is the **expected** release state: no trained model
is deployed; the P016 candidate remains offline and unpromoted.

Error handling (observed): `--url http://127.0.0.1:<closed port> --timeout 2`
→ `ERROR health … TimeoutError` (Windows retries SYN to a closed loopback
port until the timeout), 10 checks SKIP, exit 2. `--url
https://git-pipeline.metatronhost.in/auditor` → refused before any request,
exit 2.

Regression: `pytest -q` 167 passed (153 existing + 14 new; one pre-existing
Starlette TestClient deprecation warning); `pip check` clean;
`scripts/check_env.py` imports OK; `node scripts/verify-contract.mjs` 75/75.
Training suite not re-run (unchanged).

Application defects found: **none**. Runner-side issues corrected during
development (before commit): console code-page-safe output; a
payload-hygiene test that initially matched a field *name* in a legitimate
error summary.

Documentation defect fixed: the README Windows setup block (since `22b0a08`)
and two historical command lines (HANDOFF, P013 evidence) had lost their
backslashes (`.venvScriptspython.exe`, and a vertical-tab control character
in the interpreter path), so the Windows commands as written would not run.
Paths restored; no behaviour change. `.gitignore` now ignores local
`smoke-report*.json` files.

## 6. `.gitattributes`

Adds LF rules for `contracts/v1/**` and `scripts/verify-contract.mjs`. All 9
paths are already LF in the index; contracts were not regenerated and the
manifest hashes are unchanged (verifier 75/75). One local Windows working
copy (`contracts/v1/manifest.json`) is CRLF on disk from an earlier checkout;
git reports it unmodified and it was left untouched — a fresh checkout under
the new rules is LF.

## 7. Scope of this evidence — verified vs not verified

Verified here: Python service behaviour **in-process** on Windows at this
checkout.

Not verified by P029-PREP (must be recorded separately):

- The deployed VPS service (no VPS command was run; HTTP mode was not run
  against 19003 — M-D FreeBuff may be using that port).
- auditor-backend (Node) integration: at inspection it calls only
  /v1/analyze and /v1/forecast; /v1/anomalies and /v1/drift integration (P026)
  is not verified here.
- Browser journeys (simulator/auditor frontends), simulator export, and
  deployment/webhook behaviour.

## 8. What a release record must capture (Python part)

1. Deployed energy-ml-service commit (from the VPS checkout used by PM2), and
   whether it equals origin/main.
2. `runner_checkout_commit` from the smoke report, and confirmation it is the
   same checkout the service runs (HTTP mode tests the running process; the
   runner's commit alone does not prove what is deployed).
3. Returned versions: `/health` model_available; `/v1/model/info`
   contract_version, model_version, baseline_version; analyze rule,
   anomalies and drift detector versions.
4. Mode and target (`in-process`, or `http://127.0.0.1:19003`), timestamp,
   counts and exit code; any fail/error/skip with its message.
5. Whether Node (auditor-backend → Python) and browser checks were executed,
   by whom, and their results — recorded separately; this runner does not
   cover them.

## 9. Limitations

- Fixed, small synthetic fixtures check that each capability is wired and
  behaves as specified; they are not accuracy or real-building evidence.
- In-process mode verifies the checkout's code, not the running process or
  its environment; HTTP mode verifies the running process but not its commit.
- The runner reads `contracts/v1/fixtures/reference.json` and imports the
  service's synthetic builders, so it must run from a complete checkout of
  this repository.
