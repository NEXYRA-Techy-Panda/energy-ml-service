# Demo readiness — NEXYRA (release state as of 2026-09-25)

Prepared by Developer Mohan | M-C — Claude Code | P029-PREP2. Review **pending**.
Release preparation only: outstanding implementation and browser verification
are **not** marked complete here.

Sources: committed Git snapshots only (each repo's local `HEAD`, no fetch, no
uncommitted edits read), listed in
[P029_PREP2_DEMO_HANDOFF_EVIDENCE.md](P029_PREP2_DEMO_HANDOFF_EVIDENCE.md).
Demo steps: [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md).

## 1. Deployment status — supplied vs observed

| Repo | Supplied deployed baseline (assignment record) | Later committed on `main` (deployment **not observed**) |
|---|---|---|
| simulation-frontend | `b31ac37` | `dbcbee9` control-ack/reset-race fix |
| simulation-backend | `929e78e` | — |
| auditor-frontend | `6f7a94b` | — (uncommitted P027 edits exist; not an interface) |
| auditor-backend | `f3b8e2c` | `d0fcd09` P026 detectors |
| energy-ml-service | `a0a86cc` | `c49a152` smoke runner (no API change) |

Current observation by M-C: **none** (no network probe, no VPS access in this
task). The auditor's reported **502** is under **P026-R1** investigation
(owner M-D — FreeBuff); it is neither fixed nor attributed to a commit here.

Verification levels used below: **unit/mock** (automated tests, mocked
peers) · **real HTTP** (real services on isolated ports/scratch DB) ·
**browser** (human-observed UI) · **deployed** (observed on the VPS).

## 2. Capabilities

| Capability | Implementation (commit) | Highest verification | Remaining dependency / blocker | Owner |
|---|---|---|---|---|
| Simulator clock and controls | sim-backend P004 `93da205`, P008 `6d26309`, K002 `26ba717`; sim-frontend P009 `cc2fc8f`, `dbcbee9` | real HTTP (backend, temp DB); frontend unit/mock | Browser check not confirmed; `dbcbee9` deployment not observed | Kishore (K agents) |
| CSV/JSON export and monthly generation | **Not implemented** at sim-backend `929e78e` (routes: health, inventory, state, control, occupancy, calendar, devices; no export) | — | Export + monthly generation not confirmed from available evidence | Kishore |
| Auditor import, dedup, tariff, coverage | auditor-backend P006 `3154e78`; auditor-frontend P007 `9304022`, P017 `45c657e` | real HTTP (isolated backend; P017 A–F 17/17) | Browser upload/tariff not verified; public auditor currently reported 502 | M-D (backend), M-A (frontend) |
| Vacancy analysis | Python P010 `36f5832`; backend P015 `49b61fc`; frontend P019 `855879c`, P025 `3beb07b` | real HTTP (P025 A–E: 0.01 kWh, ₹0.10, fridge excluded) | Browser not verified | M-C (Python), M-D, M-A |
| Excess-consumption detection | Python P022 `b17e54b`; backend P026 `d0fcd09` (review pending) | real HTTP isolated (`check:detector-http`); Python synthetic held-out | No committed frontend UI (P027 pending); `d0fcd09` deployment not confirmed; P026-R1 | M-C, M-D, M-A |
| Gradual-trend detection | Python P024 `208417e`; backend P026 `d0fcd09` | real HTTP isolated; Python synthetic held-out 80/80 | Same as above; needs ≥ 3 weeks of data | M-C, M-D, M-A |
| Forecasting | Python P013 `7f71363`; backend P020 `a7129f2`; frontend P025 `3beb07b` | real HTTP (672 h synthetic import → 720-point month forecast) | Browser not verified; needs ≥ 168 observed hours | M-C, M-D, M-A |
| Historical analytics | backend P023 `d683578` (rooms, devices, timeseries, weekday) | real HTTP (test server, scratch DB; `npm test` 28/28 at P023) | No committed frontend consumer (P027 dashboard pending) | M-D, M-A |
| Report and ROI | frontend P014 `78e1626` printable dataset summary; economics module `abab613` on worktree branch `mohan/p028-report-math-prep` (not on `main`) | P014: build/markup only (print not browser-verified); P028-PREP: unit | Report integration (P028) pending; ROI inputs need owner decisions | M-A, M-B |
| Original/improved comparison | Storage helper only (`comparison_records` in auditor-backend `src/db/database.ts`, no route); comparison math on P028 branch | — | Not confirmed from available evidence; no improved-run generation or UI | M-B / owner decision |
| Python release smoke | energy-ml-service P029-PREP `c49a152` | in-process 11/11 (Windows) | Not yet run against the deployed interpreter | Mohan / operator |

## 3. Supported claims

| Say | Do not say |
|---|---|
| Forecast is a **statistical baseline** (`hourly-profile-median-v1`), with coverage and limitations | "AI/trained model forecast"; the HGB candidate (P016) is **offline only, not deployed** |
| Vacancy finding is a **rule-based operational-waste estimate** (device on in a vacant room beyond a grace period) | "All consumption is waste"; "guaranteed saving" |
| Excess consumption is a **deviation from earlier comparable readings** of the same device | "Fault detected", "malfunction" |
| Drift is a **sustained upward power trend under matched observed conditions** | "Efficiency loss", "degradation diagnosed" |
| Context matching **reduces** confounding; it does not establish a fault | "Root cause identified" |
| Detector magnitudes are observations, **not savings**; opportunities can overlap and are **not summed** | A combined "total savings" figure |
| Synthetic diagnostics (e.g. P022 TP 116 / FP 0 / FN 64; P024 80/80) describe **idealised synthetic data** | "Accuracy on real buildings" |
| `model_available: false` means **no trained model is deployed, by design**; all supported routes work without one | "Service is down/failing" |
| Demo data is **synthetic** (contract reference fixture or labelled generated data) | "Real building data" or "exported by the simulator" (export is not implemented) |

## 4. Judge questions — short answers

- **Where does the data come from?** Today: the contract reference fixture
  (`contracts/v1/fixtures/reference.{json,csv}`) and labelled synthetic
  datasets generated by test harnesses. The simulator runs live, but its
  export to the contract format is not implemented yet.
- **AI/statistics vs rules?** Vacancy = deterministic rule. Forecast =
  statistical median profile. Excess consumption = robust statistics
  (median/MAD threshold). Drift = Theil–Sen trend with persistence rules. A
  trained gradient-boosting forecaster exists offline only, and is not deployed.
- **How would real building data connect?** Any source that produces contract
  v1.0.1 CSV/JSON (interval energy/power per device plus room occupancy and
  temperature) can be imported. No BMS/sensor connector exists; building one
  is future work.
- **Why a simulator?** It gives controllable, reproducible scenarios with
  known ground truth (occupancy, schedules, injected changes). That lets
  detectors be tested before real data is available. Synthetic results are
  not real-building performance.
- **What is differentiated?** A working, end-to-end reproducible workflow from
  import to coverage-aware analysis, forecast and tariff cost. It separates
  measured values, estimates and what is not assessed. Market uniqueness is
  **not claimed**; no competitive evidence has been gathered.
- **How are savings and ROI supported?** Only the vacancy estimate carries
  avoidable energy/cost (tariff × kWh, for the analysed period). Forecasts
  and detector observations carry no savings. ROI/payback math is prepared
  (P028-PREP) but not integrated. It needs user-entered costs and explicit
  assumptions.
- **Who pays; what is unvalidated?** The likely buyer is a commercial
  building owner or facility manager (a hypothesis). Pricing, customer
  willingness to pay, and the first-customer timeline are **unvalidated
  owner decisions** (pricing was deferred by Mohan). Earlier hypothetical
  prices are not approved.

## 5. Judging criteria — proof available or decision missing

| Criterion (weight) | Available proof | Missing decision / gap |
|---|---|---|
| Problem and market (15) | Vacancy rule quantifies after-hours waste on reference data | Market sizing/source not evidenced |
| Revenue viability (20) | Economics math prepared (P028-PREP, unit-tested) | **Pricing and first-customer timeline — Mohan** |
| Technical execution (20) | Real-HTTP chains: import→analysis, import→forecast; Python smoke 11/11 | Browser + deployed verification; auditor 502 (P026-R1) |
| Innovation (15) | Coverage-aware detectors that separate step/offset/spike from trend | No real-building evaluation |
| UX (10) | Auditor UI: import, summary, tariff, findings, forecast (committed) | Browser walkthrough not observed; detector/analytics UI pending (P027) |
| Scale and impact (10) | Month-size import observed (P006 `check:import-scale`: 803,520 device intervals, 66 s, isolated); bounded jobs | Real deployment load not measured |
| Pitch (10) | This runbook + claims table | Rehearsal against a verified demo environment |

## 6. Final release checklist (none checked by this task)

| ☐ | Item | Owner | Evidence needed |
|---|---|---|---|
| ☐ | Auditor public health restored and verified | M-D — FreeBuff (P026-R1) | `GET …/auditor/api/v1/health` 200 observed, with the time and deployed commit |
| ☐ | Deployed commits identified (all five) | Mohan / operator | `git rev-parse HEAD` in each VPS checkout, compared with origin/main |
| ☐ | Python smoke against the existing deployed interpreter | Mohan / operator | `python -m app.smoke` in-process + `--url http://127.0.0.1:19003` output; see [P029 evidence §4, §8](P029_PYTHON_RELEASE_READINESS_EVIDENCE.md) |
| ☐ | Real simulator export imported into the auditor | Kishore (export), M-D | An export file produced by the simulator, plus its import report |
| ☐ | Browser-observed upload, analysis, forecast and tariff flow | M-A / Mohan | Human walkthrough notes or screenshots against a **named** API base |
| ☐ | Missing/insufficient data shown honestly | M-A | Browser: forecast `INSUFFICIENT_DATA`, detector `insufficient_*` statuses displayed |
| ☐ | Report contents consistent with supported evidence | M-B / M-A (P028) | Report reviewed against §3 claims |
| ☐ | Demo environment and fallback prepared | Mohan | Isolated backend + scratch DB verified; offline fallback captures ([runbook §0](DEMO_RUNBOOK.md)) |
| ☐ | Pricing / timeline confirmed | Mohan | Written owner decision |
