# energy-ml-service

Analysis and inference microservice for the NEXYRA commercial-building energy
simulation and auditing project.

- **Role**: Python + FastAPI + pandas + scikit-learn service called privately
  by `auditor-backend` for analytics support, anomaly detection, and
  next-day/week/month forecasts plus comparison support.
- **Owner**: Mohan.
- **Local port**: `8000`.

## Status (P013, 2026-09-24)

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

## Setup (Python 3.13; no PowerShell execution-policy change needed)

Windows — call the venv's interpreter directly (no `Activate.ps1`):

```powershell
& "C:UsersikramAppDataLocalProgramsPythonPython313python.exe" -m venv .venv   # or: py -3.13 -m venv .venv
.venvScriptspython.exe -m pip install -r requirements-dev.txt   # runtime only: requirements.txt
.venvScriptspython.exe scriptscheck_env.py                     # interpreter + imports
.venvScriptspython.exe -m pip check
.venvScriptspython.exe -m pytest -q
.venvScriptspython.exe -m app                                    # http://127.0.0.1:8000
```

Linux (eventual VPS; not deployed):

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
HOST=127.0.0.1 PORT=8000 .venv/bin/python -m app
# equivalent: .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Checks: `curl http://localhost:8000/health`, `curl http://localhost:8000/v1/model/info`.

## Configuration

`HOST` (default 127.0.0.1) and `PORT` (default 8000), read by `python -m app`
from the environment or a local `.env` (see `.env.example`; `.env` is
git-ignored). The service is private: only `auditor-backend` calls it (via its
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
- [Data contract v1](contracts/v1/CONTRACT.md)
- [Service interfaces](contracts/v1/API.md)
