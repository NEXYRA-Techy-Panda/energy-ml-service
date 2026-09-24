# P029-PREP2 — Demo and release handoff evidence

Developer Mohan | Agent M-C — Claude Code | P029-PREP2 | review **pending**.
Supporting release-readiness batch 28 / approximately 29. Documentation only.
Release preparation only; outstanding implementation and browser verification
are not marked complete.

## 1. Deliverables

- [DEMO_READINESS.md](DEMO_READINESS.md): deployment status (supplied vs
  observed), a capability table (commit, verification level, blocker,
  owner), supported claims, judge answers, judging-criteria table and the
  release checklist (all unchecked).
- [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md): environment prerequisites, a 3-minute
  core path, a 5-minute conditional extension and live-failure handling.
- Continuity: ACTIVE_TASK, HANDOFF, PROGRESS_LOG. PROGRESS_LOG now records
  the P029-PREP commit `c49a152`.

## 2. Sources read (committed snapshots only)

Each sibling was read with `git show HEAD:<path>` on its local `main`. There
was no fetch, no checkout, and none of the uncommitted working-tree edits
present in auditor-frontend and auditor-backend were read.

| Repo | HEAD read | Documents / files |
|---|---|---|
| energy-ml-service | `c49a152` | README, PROJECT_CONTEXT, HANDOFF, ACTIVE_TASK, PROGRESS_LOG, P010–P029 evidence, `app/{anomalies,drift}/constants.py` |
| auditor-backend | `d0fcd09` | ACTIVE_TASK, P006, P015, P020, P023, P026 evidence, AUDITOR_API_EXAMPLES, `.env.example`, `src/config.ts`, `src/routes` (comparison search), `scripts/`, package.json |
| auditor-frontend | `6f7a94b` | ACTIVE_TASK, P014, P017, P019, P025 evidence, README, `app/lib/deployment-config.ts`, `app/components/auditor-screen.tsx` (grep) |
| simulation-backend | `929e78e` | ACTIVE_TASK, HANDOFF, P004 evidence, `src/` route list |
| simulation-frontend | `dbcbee9` | ACTIVE_TASK, P009 evidence, commit `dbcbee9` stat, `app/lib/deployment-config.ts` |
| P028 worktree (`mohan/p028-report-math-prep`) | `abab613` / `ff3d624` | P028_REPORT_MATH_PREP_EVIDENCE (module surface) |

AGENTS.md: absent in energy-ml-service and in the parent folder.

## 3. Checks performed

- **Paths and scripts referenced exist at the read commits:**
  - contract fixtures `reference.{json,csv}` and `expected.json`;
  - `auditor-backend/scripts/check-{import,import-scale,analysis,forecast,detector}-http.mjs`;
  - npm scripts `build`, `start` and `check:*`;
  - `app/lib/deployment-config.ts` in both frontends;
  - `src/reporting/economics.ts` (on the P028 branch only);
  - `app/smoke.py` (this repo).
- **API routes and bodies match the committed examples:**
  - `POST /api/v1/imports` (multipart `file`);
  - `GET /api/v1/imports/:id/summary`;
  - `PUT /api/v1/imports/:id/tariff` `{inr_per_kwh}`;
  - `POST`/`GET /api/v1/analysis/jobs` (with `detector`, `reference_window`, `evaluation_window`);
  - `POST`/`GET /api/v1/forecasts`;
  - `GET /api/v1/detectors`.
- **Numbers cross-checked:**
  - `expected.json`: office 0.03 kWh; ₹10/kWh gives ₹0.30; finding light-a 0.01 kWh, ₹0.10; fridge-b 0.01 kWh total.
  - P017 A–C and P025 items 3–6 agree.
  - The Python smoke run (P029-PREP) matches: 104.8 W vs 82 W, +29.7 %.
- **Detector minimums** were taken from committed constants:
  - P022: 12 reference intervals over at least 2 h.
  - P024: 5 reference days over at least 7 days, and 10 evaluation days over at least 14 days with coverage ≥ 0.5.
  - Forecast eligibility is 168/336/672 hours (P013/P025).
- **Not run:** pytest, training, the service smoke check, servers, network probes and VPS commands. Code is unchanged since `c49a152`.

## 4. Findings recorded for the owner

1. **Frontends hard-code the public APIs** (`6f7a94b`, `b31ac37`/`dbcbee9`).
   A locally opened UI mutates the production database. A UI demo against an
   isolated backend therefore needs an owner-approved demo build (M-A /
   Kishore), otherwise the core path runs over API calls.
2. **Simulator export and monthly generation are not implemented** at
   `929e78e`: there is no export route. The only committed importable demo
   data is the synthetic contract fixture. No committed file is large enough
   for a forecast or detector demonstration; generators exist only inside
   the check scripts.
3. **No frontend consumer exists yet** for historical analytics (P023) or the
   detectors (P026): P027 is pending.
4. **P026 `d0fcd09`** is committed with completion evidence (review pending).
   Its deployment is not confirmed, and the public 502 is under P026-R1.
5. **Report and ROI:** only the P014 dataset-summary print exists on `main`.
   The P028-PREP economics are on a separate branch that has not been
   integrated.
6. **Original/improved comparison:** only a database storage helper exists;
   there is no route, generator or UI. Status: not confirmed from available
   evidence.

## 5. Claims corrected or excluded

- Excluded:
  - "trained/AI forecast" (the deployed forecast is a statistical baseline; the HGB model is offline only);
  - fault or efficiency diagnosis;
  - summed or total savings across findings;
  - real-building accuracy;
  - "simulator-exported" demo data;
  - market uniqueness;
  - approved pricing.
- `model_available: false` is described as the intended state, not a failure.
- Pricing and the first-customer timeline are marked as owner decisions for
  Mohan.

## 6. Git

- Base: `c49a152` (P029-PREP), which equalled the local `origin/main` at the
  start of this task.
- The commit contains documentation only. The hash is reported in the task's
  final report and is not written here before it exists.
- A push to `main` may invoke the existing deployment pipeline. Deployment is
  claimed only if observed.
