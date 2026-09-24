# energy-ml-service

Analysis and inference microservice for the NEXYRA commercial-building energy
simulation and auditing project.

- **Role**: Python + FastAPI + pandas + scikit-learn service called privately
  by `auditor-backend` for analytics support, anomaly detection, and
  next-day/week/month forecasts plus comparison support.
- **Owner**: Mohan.
- **Local port**: `8000`.

## Status (P010, 2026-09-24)

Routes (contract 1.0.1, all in the `{data, meta:{request_id}}` / `{error}` envelopes):

- `GET /health` → `{"status":"ok","model_available":false}`
- `GET /v1/model/info` → `model_available: false`, `model_version: null`,
  `baseline_version: null`, `contract_version: "1.0.1"`
- `POST /v1/analyze` → **deterministic rule baseline** (`method: "rule"`,
  rule `vacant-beyond-grace-v1`, finding type `vacant_but_on`): an eligible
  device operated while its room was vacant beyond its vacancy grace.
  Always-on exceptions are excluded; uncertain cases return warnings, not
  invented waste. See [P010 evidence](docs/P010_ML_FOUNDATION_EVIDENCE.md)
  for the complete request/response.
- `POST /v1/forecast` → not implemented (404).

**Model vs rule.** No trained model exists: `model_available` stays
`false` and model versions stay `null`. `/v1/analyze` is a deterministic
rule that needs no model, so it works and never returns
`MODEL_UNAVAILABLE` merely because no model exists. It returns no
probabilities and is not AI/ML. Future model-based analyses/forecasts will
report `MODEL_UNAVAILABLE` until a validated model is loaded.

**Request bounds.** Inline data only (no database, files or callbacks): at
most 2,000 device intervals and 2,000 room intervals per request (else 413
`REQUEST_TOO_LARGE`). For the 18-device office at one-minute resolution that
is roughly 111 minutes per request — **not a whole month**. The auditor
backend must window long periods and include preceding context so vacancy
grace can be established at window starts.

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
- [Data contract v1](contracts/v1/CONTRACT.md)
- [Service interfaces](contracts/v1/API.md)
