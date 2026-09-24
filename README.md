# energy-ml-service

Analysis and inference microservice for the NEXYRA commercial-building energy
simulation and auditing project.

- **Role**: Python + FastAPI + pandas + scikit-learn service called privately
  by `auditor-backend` for analytics support, anomaly detection, and
  next-day/week/month forecasts plus comparison support.
- **Owner**: Mohan.
- **Fixed port**: `19003`.

## Status (P029-PREP, 2026-09-25)

Routes (contract 1.0.1, all in the `{data, meta:{request_id}}` / `{error}` envelopes):

- `GET /health` → `{"status":"ok","model_available":false}`
- `GET /v1/model/info` → `model_available: false`, `model_version: null`,
  `baseline_version: "hourly-profile-median-v1"` (the statistical forecast
  baseline — not a trained model), `contract_version: "1.0.1"`
- `POST /v1/analyze` → **deterministic rule** (`method: "rule"`,
  `vacant-beyond-grace-v1`); see [P010 evidence](docs/P010_ML_FOUNDATION_EVIDENCE.md).
- `POST /v1/forecast` → **statistical hourly baseline** (`method:
  "statistical_baseline"`, `baseline_version: "hourly-profile-median-v1"`,
  `model_version: null`, `uncertainty: "unavailable"`): median of observed
  history by local weekday+hour → working/non-working class+hour →
  hour-of-day (disclosed fallbacks). Horizons `next_24h`, `next_7d` and
  `next_calendar_month` (the complete next **local** calendar month).
  422 `INSUFFICIENT_DATA` below 168/336/672 observed hours or when a horizon
  hour has no supported profile; ≤ 2,160 history hours (else 413). See
  [P013 evidence](docs/P013_FORECAST_BASELINE_EVIDENCE.md) for the complete
  request/response, time semantics and auditor integration.

- `POST /v1/anomalies` → **excess-consumption deviation detector**
  (additive P022 extension; `detector_version: "excess-power-mad-v1"`,
  `method: "rule"`, `technique: "robust_median_mad"`): compares each
  device's fully-on evaluation intervals with its OWN earlier comparable
  reference intervals (comfort-dependent AC/refrigerator conditioned on room
  temperature ±1 °C and occupancy ±1); threshold = median + max(4 × 1.4826 ×
  MAD, max(10 W, 10 %)); ≥ 12 reference intervals over ≥ 2 h. Explicit
  statuses + coverage + exclusions; not a malfunction diagnosis; no drift
  detection. ≤ 2,000 device + 2,000 room intervals per section, body ≤ 16 MiB.
  See [P022 evidence](docs/P022_EXCESS_CONSUMPTION_EVIDENCE.md).

- `POST /v1/drift` → **gradual upward power-trend detector** (additive P024
  extension; `detector_version: "gradual-power-trend-v1"`, `method: "rule"`,
  `technique: "theil_sen_context_normalised_daily"`): same request structure
  and limits as `/v1/anomalies`; context-normalised daily summaries of
  comparable fully-on observations (reference ≥ 5 days over ≥ 7; evaluation
  ≥ 10 days over ≥ 14 with ≥ 50 % coverage); Theil–Sen trend ≥ 10 % and
  ≥ 10 W with persistence → "Sustained upward power trend under matched
  observed conditions"; steps, offsets and spikes are described separately.
  Not an efficiency or fault diagnosis. See
  [P024 evidence](docs/P024_GRADUAL_TREND_EVIDENCE.md).

**Model vs baseline vs rule.** No trained model exists: `model_available`
stays `false` and `model_version` stays `null`. The analysis rule and the
forecast baseline need no trained model, so they work and never return
`MODEL_UNAVAILABLE` merely because none exists. Neither returns
probabilities, confidence or prediction intervals, and neither is AI/ML.

**Request bounds and context.** Analyze: ≤ 2,000 device + 2,000 room
intervals (~111 minutes of the 18-device office) — the auditor must window
long periods with preceding context. Forecast: ≤ 2,160 complete hourly
points (90 days) on the origin's hourly grid; missing hours are gaps, never
zero.

**Offline evaluation (synthetic data only):**
`.venv\Scripts\python.exe scripts\evaluate_forecast_baseline.py` —
chronological holdout vs repeat-last-day; results describe synthetic data,
not real-building accuracy.

**Offline trained-forecast candidate (P016) — NOT deployed.** A small
scikit-learn HistGradientBoosting candidate (origin-anchored features, direct
multi-horizon strategy) can be trained, evaluated against the P013 baseline
and repeat-last-day on temporal train/validation/test splits, saved as a
local bundle and reloaded for offline prediction:
`.venv\Scripts\python.exe -m app.training.cli {generate|validate|train|evaluate|suite|predict} …`
(see [P016 evidence](docs/P016_TRAINED_FORECAST_CANDIDATE_EVIDENCE.md)).
On SYNTHETIC data it beat the baseline in 15/27 cells but failed badly under
a regime change, so **the baseline stays the production forecaster**;
`model_available` stays `false`. `data/` and `artifacts/` (datasets,
model bundles, reports) are git-ignored and generated locally.

## Setup (Python 3.13; no PowerShell execution-policy change needed)

Windows — call the venv's interpreter directly (no `Activate.ps1`):

```powershell
& "C:\Users\vikram\AppData\Local\Programs\Python\Python313\python.exe" -m venv .venv   # or: py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # runtime only: requirements.txt
.venv\Scripts\python.exe scripts\check_env.py                     # interpreter + imports
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m app                                    # http://127.0.0.1:19003
```

Linux (eventual VPS; not deployed):

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
HOST=127.0.0.1 .venv/bin/python -m app
# Equivalent explicit ASGI command: .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 19003
```

Checks: `curl http://localhost:19003/health`, `curl http://localhost:19003/v1/model/info`.

### Release smoke check (P029-PREP)

One command verifies the supported capabilities (health/model info, analyze,
forecast, anomalies, drift, validation) and exits 0 / 1 (application failure)
/ 2 (target unreachable or bad target):

```powershell
.venv\Scripts\python.exe -m app.smoke                               # in-process (default; no listener)
.venv\Scripts\python.exe -m app.smoke --json smoke-report.json      # plus machine-readable report
.venv\Scripts\python.exe -m app.smoke --url http://127.0.0.1:19003  # explicit loopback HTTP target only
```

On the VPS use the running service's existing interpreter (see
[P029 evidence](docs/P029_PYTHON_RELEASE_READINESS_EVIDENCE.md) §4). Python
checks do not cover Node integration, browsers or deployment.

## Configuration

`HOST` defaults to `127.0.0.1` and may be read from the environment or a local
`.env` (see `.env.example`; `.env` is git-ignored). The production HTTP port
is fixed in source at `19003`; `PORT` is intentionally ignored. The service is
private: only `auditor-backend` calls it (via its
`ML_SERVICE_URL`, from F4); browsers never do. Keep it bound to 127.0.0.1.

Windows note: if pandas fails with "An Application Control policy has blocked
this file", Windows Smart App Control is blocking its compiled extensions — see
[F2-B evidence](docs/F2_B_EVIDENCE.md).

Docs:

- [Project context](docs/PROJECT_CONTEXT.md)
- [Workspace map](docs/WORKSPACE_MAP.md)
- [Handoff](docs/HANDOFF.md)
- [Agent start prompt](docs/AGENT_START_PROMPT.md)
- [Active task](docs/ACTIVE_TASK.md)
- [Progress log](docs/PROGRESS_LOG.md)
- [F1 evidence](docs/F1_EVIDENCE.md)
- [F2-B evidence](docs/F2_B_EVIDENCE.md)
- [P010 ML foundation evidence](docs/P010_ML_FOUNDATION_EVIDENCE.md)
- [P013 forecast baseline evidence](docs/P013_FORECAST_BASELINE_EVIDENCE.md)
- [P016 trained forecast candidate evidence](docs/P016_TRAINED_FORECAST_CANDIDATE_EVIDENCE.md)
- [P021 temporal boundary evidence](docs/P021_TEMPORAL_BOUNDARY_EVIDENCE.md)
- [P022 excess-consumption detector evidence](docs/P022_EXCESS_CONSUMPTION_EVIDENCE.md)
- [P024 gradual trend evidence](docs/P024_GRADUAL_TREND_EVIDENCE.md)
- [P029 Python release-readiness evidence](docs/P029_PYTHON_RELEASE_READINESS_EVIDENCE.md)
- [Demo readiness](docs/DEMO_READINESS.md) · [Demo runbook](docs/DEMO_RUNBOOK.md) · [P029-PREP2 evidence](docs/P029_PREP2_DEMO_HANDOFF_EVIDENCE.md)
- [Data contract v1](contracts/v1/CONTRACT.md)
- [Service interfaces](contracts/v1/API.md)
