# energy-ml-service

Analysis and inference microservice for the NEXYRA commercial-building energy
simulation and auditing project.

- **Role**: Python + FastAPI + pandas + scikit-learn service called privately
  by `auditor-backend` for analytics support, anomaly detection, and
  next-day/week/month forecasts plus comparison support.
- **Owner**: Mohan.
- **Local port (proposed)**: `8000`.
- **State at F0 (2026-09-24)**: empty repository — documentation only, no code;
  Python `3.12` + venv + `requirements.txt` proposed for F2.
  See `docs/HANDOFF.md` for verified state.

Docs:

- [Project context](docs/PROJECT_CONTEXT.md)
- [Workspace map](docs/WORKSPACE_MAP.md)
- [Handoff](docs/HANDOFF.md)
- [Agent start prompt](docs/AGENT_START_PROMPT.md)
- [Active task](docs/ACTIVE_TASK.md)
- [Progress log](docs/PROGRESS_LOG.md)
- [F1 evidence](docs/F1_EVIDENCE.md)
- [Data contract v1](contracts/v1/CONTRACT.md)
- [Service interfaces](contracts/v1/API.md)
