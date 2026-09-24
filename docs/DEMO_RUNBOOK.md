# Demo runbook — NEXYRA

Prepared by Developer Mohan | M-C — Claude Code | P029-PREP2. Review **pending**.
Capability status and claims: [DEMO_READINESS.md](DEMO_READINESS.md). Known
answers below come from committed evidence (auditor-backend P006/P015,
auditor-frontend P017/P025, contract fixture `expected.json`). Nothing in
this runbook has been rehearsed yet.

## 0. Before the demo — environment (mandatory)

**Never run a mutating step against the shared production database.** Import,
tariff, analysis and forecast requests all write to the auditor database.

1. **Check the API base first.** The committed auditor frontend (`6f7a94b`)
   hard-codes `https://git-pipeline.metatronhost.in/auditor` in
   `app/lib/deployment-config.ts` and shows the backend URL on screen. A
   locally opened frontend therefore still talks to the **public production
   API**. If the UI shows that URL, do **not** use it for upload, tariff or
   analysis. The simulator frontend likewise hard-codes `…/sim`.
2. **Isolated demo environment (recommended).** On the demo laptop (not the
   VPS), with no other process on the fixed ports 19002/19003 of that
   machine:
   - Python: `energy-ml-service\.venv\Scripts\python.exe -m app` (listens on 127.0.0.1:19003).
   - Auditor backend: `npm run build`, then start with
     `DATABASE_PATH` set to a **new scratch file outside the repo** in a folder
     created beforehand (for example
     `$env:DATABASE_PATH="$env:TEMP\nexyra-demo\auditor.sqlite"; npm start`).
     It listens on 127.0.0.1:19002 and calls Python at `ML_SERVICE_URL`
     (default `http://127.0.0.1:19003`).
   - Verify: `curl.exe http://127.0.0.1:19002/api/v1/health` and
     `energy-ml-service\.venv\Scripts\python.exe -m app.smoke` (in-process, 11/11 expected).
3. **UI against the isolated backend is not available from committed `main`**,
   because the frontend base URL is fixed. Either Mohan/M-A provides an
   approved demo build pointed at the isolated backend, or the core path is
   shown through API calls (below) with the UI shown read-only.
4. **Fallback captures.** Make these during a rehearsal on the isolated
   environment: saved JSON responses or screenshots for every step below,
   each labelled with the date, the commits and "isolated rehearsal". Show
   them if a live step fails, and say that they are captures.

Commands below assume PowerShell in `K:\NEXYRA\auditor-backend` against the
isolated backend (`$B = "http://127.0.0.1:19002/api/v1"`).

## 1. Core path — 3 minutes

Dataset for all core steps: the contract reference fixture
`contracts/v1/fixtures/reference.json` (and `reference.csv`). It is
**synthetic, hand-computed, two minutes long, with 4 device + 4 room
intervals**. It was **not** produced by the simulator (simulator export is
not implemented).

| # | Time | Capability | Action | Expected observable result | Honest fallback |
|---|---|---|---|---|---|
| 1 | 0:00–0:20 | Disclosure | Say: "All data today is synthetic demonstration data; no real building is measured." | Summary later shows `synthetic: true` with its label | — (always say it) |
| 2 | 0:20–0:50 | Import + dedup (auditor-backend P006) | `curl.exe -F "file=@contracts/v1/fixtures/reference.json" $B/imports`, then the same with `reference.csv` | JSON: **201**, `status: accepted`, new `dataset_id`. CSV: **200**, same `dataset_id`, `already_imported: true` (no duplicate) | Show capture; state "import verified over real HTTP on an isolated backend (P017 A–F 17/17), not in a browser" |
| 3 | 0:50–1:40 | Historical energy + tariff cost | `curl.exe $B/imports/<id>/summary`; then `PUT $B/imports/<id>/tariff` with `{"inr_per_kwh": 10}`; re-read summary | Energy **0.03 kWh**, cost `null` before tariff. After ₹10/kWh: cost **₹0.30**. Coverage 4 device + 4 room intervals; `gap_assessment.status: not_performed` | Capture; explain cost = tariff × measured interval energy |
| 4 | 1:40–2:30 | Vacancy analysis (P010 rule via P015 jobs) | `POST $B/analysis/jobs` `{"dataset_id":"<id>"}` → poll `GET $B/analysis/jobs/<job_id>` | `completed`; **1 finding**: `light-a`, `vacant_but_on`, method `rule`, **0.01 kWh**, **₹0.10** estimated avoidable at ₹10/kWh; always-on **`fridge-b` excluded** | Capture; or `python -m app.smoke` line `analyze_vacancy_reference_fixture` (Python only) |
| 5 | 2:30–3:00 | Honest framing | State the finding's suggested action: switch off the Room A light when the room is vacant (the fixture policy uses a zero-second grace period) | — | — |

Step 5 script — measured vs estimated vs not assessed:

- **Measured (synthetic input):** 0.03 kWh interval energy. **Derived:** ₹0.30
  = ₹10/kWh × 0.03 kWh.
- **Estimated:** 0.01 kWh / ₹0.10 avoidable. This is a rule-based
  operational-waste estimate for this two-minute window only, not a
  guaranteed saving. The rest of the consumption is **not** called waste.
- **Not assessed:** faults, gaps (`not_performed`), ROI/payback, and
  forecasts or trends. This dataset is far too short for those.

## 2. Optional extension — +5 minutes

Only run a step whose dataset and interface are ready. Each needs its own
dataset. **The reference fixture cannot show a successful forecast or trend.**
This task does not produce any new large dataset.

| # | Capability | Dataset prerequisite | Action | Expected result | Honest fallback |
|---|---|---|---|---|---|
| E1 | Insufficient data shown honestly (P020) | Reference fixture (already imported) | `POST $B/forecasts` `{"dataset_id":"<id>","horizon":"next_24h"}` → poll `GET $B/forecasts/<id>` | Failed job, `INSUFFICIENT_DATA`: needs ≥ 168 complete observed hours; missing hours are not treated as zero | Capture from P025 evidence (item 5) |
| E2 | Forecast (P013 statistical baseline via P020/P025) | Labelled synthetic contract dataset with **≥ 168** complete observed hours (next_24h); 336 for 7 days; 672 for next_calendar_month. **No committed demo file exists.** The P020 generator is inside `auditor-backend/scripts/check-forecast-http.mjs` (in memory) | Import it, set the tariff, submit the forecast | Hourly points plus total, labelled `statistical_baseline`, `model_version: null`, limitations. Reference run (P025): 672 h → 720 points, total ≈ 10.80 kWh, ₹10/kWh re-costs the same job | Say: "forecast verified over real HTTP with a 672-hour synthetic dataset (P025); not shown live today" |
| E3 | Excess-consumption deviation (P022 via P026 `d0fcd09`) | Per device: ≥ 12 comparable fully-on reference intervals spanning ≥ 2 h, reference window ending before evaluation. **No committed demo file.** Backend `d0fcd09` deployment not confirmed | `POST $B/analysis/jobs` with `"detector":"excess_consumption"`, `reference_window`, `evaluation_window` | `findings_detected` with observed vs expected vs threshold, **or** an explicit `insufficient_reference` / exclusions. **No UI** (P027 pending) | `python -m app.smoke`: `anomalies_excess_deviation` (104.8 W vs threshold 82 W, synthetic) and `anomalies_insufficient_reference` |
| E4 | Gradual upward trend (P024 via P026) | Reference ≥ 5 supported days over ≥ 7 days, then evaluation ≥ 10 supported days over ≥ 14 days (≥ 3 weeks in total). **No committed demo file** | Same, with `"detector":"gradual_trend"` | `findings_detected` (sustained upward power trend) **or** `insufficient_history`; no savings fields | `python -m app.smoke`: `drift_sustained_trend` (+29.7 %, synthetic) and `drift_insufficient_history` |
| E5 | Simulator live clock/controls | Isolated simulator backend + a frontend pointed at it (committed frontend points at the public `…/sim`) | Start/pause/speed; watch clock, occupancy, device power | Live state updates (verified over real HTTP; browser not confirmed) | Describe; state that export to the auditor is **not implemented** |

Language for E2–E4: forecast = statistical baseline, not a trained model.
Deviation = compared with earlier comparable readings. Trend = under matched
observed conditions. Neither E3 nor E4 is a fault diagnosis or a saving.
Never add E3/E4 magnitudes to the vacancy estimate.

## 3. If something fails live

- Health not 200, or a job stuck: switch to captures, and say "isolated
  rehearsal capture from <date>".
- `model_available: false` is **expected** (no trained model is deployed). It
  is not a failure.
- Public auditor 502: this is under P026-R1 investigation. Do not demo from
  production, and do not speculate about the cause.
