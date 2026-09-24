# HANDOFF — energy-ml-service

## 0. Continuity and current layer (F0.1, 2026-09-24)

- Current layer: **F1** (shared contract v1.0.0) — status
  **blocked** (contract authored + verified; commit/push await git identity),
  review **pending**. Contract: **1.0.0 defined** (canonical
  `simulation-backend/contracts/v1/`, mirrored to siblings).
- Continuity files: [ACTIVE_TASK.md](ACTIVE_TASK.md) and [PROGRESS_LOG.md](PROGRESS_LOG.md).
- Continuation procedure for a replacement agent: read `AGENTS.md` (absent at
  F0.1 — record if still absent), then `PROJECT_CONTEXT.md`, `WORKSPACE_MAP.md`,
  this `HANDOFF.md`, `ACTIVE_TASK.md`, and recent `PROGRESS_LOG.md` entries;
  inspect `git branch/status/log` and source; reconcile docs with code; resume
  the ACTIVE_TASK next action. Do not restart completed work. See
  [AGENT_START_PROMPT.md](AGENT_START_PROMPT.md) for the full protocol.
- Verified vs planned: **verified** = §2 state below (empty repo on `main`,
  no commits, docs-only untracked files, origins/ports/tooling as measured;
  Python still not installed at F0.1). Everything marked "Not implemented" or
  "planned" is **not** built. This repo has NOT completed application setup —
  F2 has not run.
- Layer clarifications: **F1 is contract work and does not require Python.**
  Python installation/runtime verification belongs to **F2 for this repo
  (energy-ml-service)** — its top blocker until then. Auditor Node work can
  proceed independently; Python is required only for the relevant
  auditor↔Python integration checks (F4). Runtime recommendations from F0
  (Python `3.12`, venv+pip) remain **provisional until checked against chosen
  dependency versions and official compatibility documentation during F2**.
- F0 review status: accepted by architecture lead based on supplied evidence;
  local files were not directly inspected by the lead.
- F1 addendum (2026-09-24, completed, review pending): contract v1.0.0 defined;
  this repo holds a byte-identical mirror under `contracts/v1/` (canonical:
  `simulation-backend/contracts/v1/`; see `contracts/v1/manifest.json`).
  `node scripts/verify-contract.mjs` → 49 passed, 0 failed in all five repos
  (semantic checks only; formal schema validation is F2). Links:
  [contract](contracts/v1/CONTRACT.md), [schema](contracts/v1/dataset.schema.json),
  [CSV](contracts/v1/CSV_COLUMNS.md), [API](contracts/v1/API.md),
  [evidence](F1_EVIDENCE.md), [active task](ACTIVE_TASK.md),
  [progress](PROGRESS_LOG.md).
- Dated corrections (history preserved in PROGRESS_LOG): Python 3.13.15
  (64-bit, pip 26.2.1) verified at the supplied interpreter path — "Python not
  installed" no longer a current blocker; installation/runtime verification for
  dependency compatibility remains F2 work for this repo (F1 needs no Python);
  F0.1 "read-only sibling" wording corrected — F0.1 explicitly covered all five
  repositories; runtime recommendations stay provisional until F2; hosting plan
  — frontends on Vercel, Node backends + Python service on Mohan's VPS (no
  deployment in F1); from F1 onward completed layer work is committed and
  pushed (F0/F0.1 no-push was historical only).

## 1. Purpose and owner

- **Purpose**: Analysis and inference microservice. Python + FastAPI + pandas +
  scikit-learn service called server-side by the auditor backend for office/
  room/device analytics support, waste/anomaly detection support, and
  next-day / next-week / next-calendar-month forecasts plus original/improved
  comparison support. Never called directly by browsers; owns no SQLite;
  preserves time order in evaluation; model selection depends on measured
  validation results; synthetic outputs are explicitly labelled.
- **Owner (foundation + long-term)**: Mohan.

## 2. Current verified state (F0, 2026-09-24)

- Local path: `K:\NEXYRA\energy-ml-service` (portable: `../energy-ml-service`).
- Remote: `https://github.com/NEXYRA-Techy-Panda/energy-ml-service.git`
  (verified; fetch OK).
- Branch: `main`. HEAD: **No commits yet**.
- Working tree before F0 docs: clean (only `.git/`).
- After F0 docs (uncommitted): new untracked `docs/PROJECT_CONTEXT.md`,
  `docs/WORKSPACE_MAP.md`, `docs/HANDOFF.md` (this file),
  `docs/AGENT_START_PROMPT.md`, `README.md`. Not committed/pushed.
- Parent is not a Git repository. No `AGENTS.md` found at F0.
- Tooling: Git `2.55.0.windows.5`; Python **not installed** (WindowsApps shims
  only); `pip`/`py` not recognised; Node `v24.21.0` present but not used here.
  Proposed port `8000` free at F0.
- Application state: **Not implemented** — no `requirements.txt`, no `app/`,
  no venv, no models.

## 3. Completed layers and evidence

- **F0 (in review)**: cloned empty repo; verified origin/branch/HEAD/status;
  fetched; recorded tooling/ports; proposed `venv` + `pip` +
  `requirements.txt` + Python `3.12`; created docs. Evidence in F0 report.
- **F1–F6**: Not implemented. No training, no endpoints.

## 4. Pre-existing implementation discovered during inspection

None. Empty repository; nothing to preserve.

## 5. Planned next layers

- **F1**: shared contract — auditor↔Python schemas (analysis/forecast/
  comparison payloads, horizon definitions, UTC/Asia-Kolkata, kWh rules,
  time-ordered evaluation, labelling of synthetic results).
- **F2**: Python `3.12` venv + `requirements.txt` (FastAPI, uvicorn, pandas,
  scikit-learn, pydantic — pins in F2) + `/health` shell; **do not train yet**.
- **F3**: N/A (no SQLite in Python service) — document; input validation only.
- **F4**: private HTTP wiring to auditor-backend (`ML_SERVICE_URL`), CORS/
  auth boundaries (no browser access).
- **F5**: reference-data alignment (rooms/devices/tariff-aware features).
- **F6**: verified end-to-end (auditor upload → backend → Python → results).

## 6. Prerequisites

- Install Python `3.12.x` (python.org Windows installer recommended; confirm
  source) + `pip` + `venv` before F2. Missing at F0 — top blocker for this repo.
- Sibling `../auditor-backend` (port `4001`) from F4 onward.
- F1 contract first. No Node/npm dependency for this repo.

## 7. Actual run/check commands, if implemented

No app commands exist. F0 checks:

```powershell
git -C energy-ml-service rev-parse --show-toplevel
git -C energy-ml-service remote -v
git -C energy-ml-service branch --show-current; git -C energy-ml-service status -sb
git -C energy-ml-service rev-parse HEAD   # unknown revision — no commits
git -C energy-ml-service log --oneline -5 # no commits yet
git -C energy-ml-service fetch --all
git -C energy-ml-service ls-remote --heads origin  # empty
git --version
python --version; pip --version; py --version  # all fail — Python not installed
netstat -ano | Select-String ':3000 |:3001 |:4000 |:4001 |:8000 '  # no matches
```

No `pip install`, no `uvicorn`, no `pytest` — do not invent. Do not install
runtimes during F0.

## 8. Configuration names without secret values

Proposed only (no `.env` at F0):

- `PORT` / `HOST` → `8000` / localhost (F2/F4 finalise; e.g. `uvicorn` host/port).
- Any API keys/auth between auditor-backend and Python to be defined in F1/F4
  — no values at F0, never commit secrets.
- No DB paths (no SQLite here).

## 9. Contracts and external dependencies

- **F1 contract**: Not implemented.
- **Planned**: serves auditor-backend over private HTTP only. No browser
  access, no SQLite, no simulator calls.
- **Python deps**: none pinned yet (F2 creates versioned `requirements.txt`).

## 10. Database/migration status

Not applicable. No database in this service. No migrations/seeds. Inputs are
validated payloads from the auditor backend, not DB files.

## 11. Known issues and blockers

1. **Python not installed** — must resolve before F2 (confirm `3.12.x` patch +
   installer source).
2. Empty remote — greenfield.
3. Dependency pins (FastAPI/uvicorn/pandas/sklearn/numpy/scipy) undecided
   until F2 after Python lands.
4. F0 docs uncommitted — pending review.

## 12. Deferred features

Per shared context: ML training (none in F0–F2), advanced tariffs, live mode,
sensor/BMS, realistic physics, doodle occupants. Model selection only on
measured validation; preserve time order; label synthetic results.

## 13. Last verification date and relevant existing commit references

- Date: 2026-09-24. No commits. F0 docs untracked, pending review.

## 14. Instructions to update this document after every completed layer

After each layer, update date, branch/HEAD, §§2–3/7–11 with actual files,
commands and results; preserve history; keep §§1/12/14 unless scope formally
changes. Return updated sections as evidence.
