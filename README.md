# energy-ml-service

Analysis and inference microservice for the NEXYRA commercial-building energy
simulation and auditing project.

- **Role**: Python + FastAPI + pandas + scikit-learn service called privately
  by `auditor-backend` for analytics support, anomaly detection, and
  next-day/week/month forecasts plus comparison support.
- **Owner**: Mohan.
- **Local port**: `8000`.

## Status (F2-B, 2026-09-24)

FastAPI scaffold implemented; review pending. Routes: `GET /health`
(`status: "ok"`, `model_available: false`) and `GET /v1/model/info`
(versions `null`, `model_available: false`, `contract_version: "1.0.1"`).
No model is trained or loaded; `/v1/analyze` and `/v1/forecast` are not
implemented. Evidence: [F2-B evidence](docs/F2_B_EVIDENCE.md).

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
- [Data contract v1](contracts/v1/CONTRACT.md)
- [Service interfaces](contracts/v1/API.md)
