# P016_TRAINED_FORECAST_CANDIDATE_EVIDENCE — trained forecast candidate (M2)

Agent B — Claude Code | P016 | M2. Owner Mohan. Date 2026-09-24. Scope:
`energy-ml-service` only. Implementation is **completed**; review is
**pending**. The commit hash is reported in the P016 return report after the
push.

> **Status boundary.**
> - **Candidate trained offline:** yes.
> - **Candidate evaluated:** yes, on SYNTHETIC data only.
> - **Candidate deployed or available through the API:** **no.** That is not
>   part of P016. `/v1/forecast` still serves the P013 baseline,
>   `model_available` stays `false`, and `model_version` stays `null`.
>
> Synthetic results say nothing about real-building accuracy.

## Starting state

- No `AGENTS.md`. `main` was at `7f71363` (P013, accepted as a statistical
  baseline based on reported evidence), equal to `origin/main`, with a clean
  tree.
- The contract is unchanged (verifier 75/75).
- No new dependencies: scikit-learn 1.9.1, numpy 2.5.3 and joblib 1.6.0 were
  already pinned.

## 1. Evaluation-label correction (P013)

- **What was wrong:** P013's "aggregate energy error" was computed over
  **common scored hours** only, i.e. withheld hours that were observed and
  predicted by both methods. Because 5 % of the synthetic hours were missing,
  it covered 639 of 672 expected hours (24 h and 7 d) and 1,343 of 1,416
  (month). Yet it was labelled a per-origin aggregate error, and the P013
  report called it "total energy per forecast".
- **What changed:** only the labels. Calculation and numbers are unchanged:
  - `app/forecast/evaluation.py` `Score` now carries `expected_hours` and
    `energy_error_common_kwh`;
  - `scripts/evaluate_forecast_baseline.py` reports `hours_expected`,
    `hours_scored_common` and `energy_error_over_common_scored_hours_kwh`;
  - `docs/P013_FORECAST_BASELINE_EVIDENCE.md` has a dated correction note and
    relabelled output.
- **P016 uses the same convention:** comparable methods are always scored on
  identical timestamps, and expected vs scored hours are reported.

## 2. Training input and provenance

- **Format** `nexyra-hourly-training-v1` (`app/training/input.py`) is
  separate from the telemetry contract. It is one JSON file per series:
  - `series_id`, `timezone` (Asia/Kolkata), `calendar.working_days_iso`;
  - `provenance{synthetic, source, description, scenario?, seed?, dataset_id?, run_id?, exported_utc?, generated_utc?}`;
  - `points[{start_utc, energy_kwh}]`.
- **Validation:**
  - every point is a **complete** hour on one grid (full hour in UTC or on
    the local clock);
  - energy is finite and non-negative;
  - rejected: invalid timestamps, conflicting duplicates, mixed grids
    (incompatible series), unknown fields, unsupported timezones,
    injected-fault fields anywhere, NaN/Infinity;
  - identical duplicates are deduplicated and counted;
  - **missing hours stay missing** and are never zero.
- **Actual provenance in P016: SYNTHETIC only.** No authorised real dataset
  was present. Every series comes from `app/training/synthetic.py` and is
  marked `synthetic: true`. Generated files live in `data/training/`
  (git-ignored).

| Scenario | Pattern |
|---|---|
| `weekly_stable` | base 0.45 kWh/h; working hours 09–18 +5.0 (Mon +0.4, 13:00 −1.5); ±8 % noise; 3 % missing |
| `trend_regime` | weekly pattern with working load **+0.1 %/day (trend)** and a **regime change on day 330**: base +0.25 kWh/h and Saturday 09–13 +3.0 (the documented calendar is not updated); ±8 % noise; 3 % missing |
| `seasonal_ac` | weekly pattern + **seasonal** cooling load 2.5 × max(0, sin(2π(doy−60)/365)) in working hours; ±10 % noise; 5 % missing |

- **Series length:** 430 days from 2025-10-06 local.
- **Data seeds:** fixed in advance at **101, 202, 303** for every scenario,
  and **all are reported**; no seed was cherry-picked.
- **Model seed:** 0.

### Supplying real audited data later

1. Auditor-backend (its owner) exports the dataset's audited device
   intervals. Nobody reads another service's SQLite directly.
2. Sum the device energy into complete local hours (Asia/Kolkata:
   `[HH:30Z, HH+1:30Z)`). Omit any hour lacking complete coverage; don't zero
   it.
3. Write a `nexyra-hourly-training-v1` file with `provenance.synthetic:
   false`, `source: "auditor-backend export"`, `dataset_id`, `run_id` and
   `exported_utc`, plus the calendar in force.
4. Run `validate`, then `evaluate`. Keep real datasets out of Git (under
   `data/`, which is ignored).

## 3. Model, features and multi-step strategy

- **Model:** scikit-learn `HistGradientBoostingRegressor` (CPU, seconds).
  - `early_stopping=False`, because HGB's automatic early stopping would take
    a random, non-temporal validation split.
  - `random_state=seed`.
  - Predetermined configurations (no search):
    - `hgb-mae-small`: absolute_error, learning rate 0.05, 200 iterations,
      15 leaves, min leaf 20;
    - `hgb-mse-small`: the same with squared_error;
    - `hgb-mae-medium`: absolute_error, 0.05, 400 iterations, 31 leaves, min
      leaf 40.
- **Features** (`origin-anchored-v1`, `app/training/features.py`) for target
  hour t and origin o:
  - local hour, local ISO weekday, working-day flag, lead days;
  - the median of history at the same weekday+hour and at the same
    day-class+hour;
  - the last observed value at the same local hour;
  - the mean of the last 7 days and the last 28 days;
  - the weekday+hour support count.
- **Multi-step strategy: direct, not recursive.**
  - Every feature for every horizon hour (up to the month horizon, 62 days
    of lead) is computed only from the local calendar and observations that
    end at or before the origin (the latest ≤ 2,160, as in production).
  - No prediction is fed back, and no horizon actual can enter.
- **Missing values:** a feature with no supporting observations is NaN, never
  0. HGB's native NaN handling is the explicit missing-data strategy; no
  imputer is fitted.
- **Not used** (not available at prediction time or forbidden): future actual
  consumption, observed future temperature, realised occupancy, fault labels.
- **Training rows:** origins at every local midnight from day 14 to the
  cutoff, leads 0 to 62 days. A row exists only if its target hour ends at
  or before the cutoff and was observed. Missing targets produce no row.
- **Clipping:** negative predictions are clipped to 0 kWh, identically in
  evaluation and bundle inference.
- **Eligibility:** the candidate forecasts an origin only if at least 168
  observed hours end at or before it. Otherwise it records a failure.

## 4. Temporal splits and leakage protections

- **Splits** are relative to the first local midnight and are the same for
  every run: train = hours ending at or before day 280; validation = origins
  in days [280, 350); test = origins in days [350, 430).
- **Evaluation windows:** validation and test targets end inside their own
  window.
- **Horizon origins:**
  - next_24h: every local midnight;
  - next_7d: every local Monday midnight;
  - next_calendar_month: local midnight on the 15th, when the whole next
    local month fits inside the window.
- **Protocol:**
  1. Train each config on hours ending at or before `train_end`.
  2. Pick the lowest mean validation MAE across horizons. The **selection
     is frozen** before any test forecast.
  3. Refit the frozen config on all hours ending at or before
     `validation_end` (train ∪ validation, all earlier than test).
  4. Evaluate test origins with repeat-last-day, the P013 baseline and the
     candidate.
- **Fairness:** an origin is **eligible** only if all three methods
  forecast it; failures are counted per method. Metrics use **common scored
  hours** (observed and predicted by every method).
- **Tests enforce:**
  - poisoned post-origin data leaves every feature unchanged at leads up to
    45 days;
  - poisoned post-cutoff data leaves the trained model unchanged;
  - split and window boundaries;
  - a selection recorded and training/test order enforced (the test window
    only after freezing and refitting);
  - identical-timestamp scoring, with failures excluding origins for all
    methods.

## 5. Results (SYNTHETIC; common scored hours)

### Test results per run (common scored hours; SYNTHETIC)

| Scenario | Data seed | Horizon | Origins (eligible) | Failures r/b/c | Hours expected | Hours scored (common) | MAE repeat-last-day | MAE baseline | MAE candidate | Mean abs energy error over common scored hours / origin: r / b / c (kWh) |
|---|---|---|---|---|---|---|---|---|---|---|
| weekly_stable | 101 | next_24h | 80 (80) | 0/0/0 | 1920 | 1860 | 0.704 | 0.118 | 0.114 | 14.30 / 0.76 / 0.72 |
| weekly_stable | 101 | next_7d | 11 (11) | 0/0/0 | 1848 | 1791 | 1.363 | 0.118 | 0.113 | 216.65 / 2.83 / 2.81 |
| weekly_stable | 101 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 695 | 0.712 | 0.123 | 0.117 | 365.59 / 1.50 / 3.37 |
| weekly_stable | 202 | next_24h | 80 (80) | 0/0/0 | 1920 | 1855 | 0.698 | 0.119 | 0.113 | 14.26 / 0.91 / 0.90 |
| weekly_stable | 202 | next_7d | 11 (11) | 0/0/0 | 1848 | 1784 | 1.357 | 0.118 | 0.111 | 214.94 / 3.13 / 3.22 |
| weekly_stable | 202 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 695 | 0.682 | 0.118 | 0.111 | 360.59 / 10.20 / 7.81 |
| weekly_stable | 303 | next_24h | 80 (80) | 0/0/0 | 1920 | 1860 | 0.698 | 0.121 | 0.116 | 14.00 / 0.89 / 0.90 |
| weekly_stable | 303 | next_7d | 11 (11) | 0/0/0 | 1848 | 1791 | 1.332 | 0.119 | 0.114 | 212.32 / 1.98 / 2.25 |
| weekly_stable | 303 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 694 | 0.703 | 0.119 | 0.119 | 364.19 / 8.05 / 10.61 |
| trend_regime | 101 | next_24h | 80 (80) | 0/0/0 | 1920 | 1857 | 0.960 | 0.270 | 1.444 | 19.21 / 4.33 / 26.91 |
| trend_regime | 101 | next_7d | 11 (11) | 0/0/0 | 1848 | 1785 | 1.924 | 0.279 | 1.373 | 301.53 / 32.00 / 174.31 |
| trend_regime | 101 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 691 | 0.863 | 0.386 | 1.674 | 365.92 / 233.47 / 900.09 |
| trend_regime | 202 | next_24h | 80 (80) | 0/0/0 | 1920 | 1859 | 0.965 | 0.266 | 0.357 | 19.06 / 4.38 / 2.94 |
| trend_regime | 202 | next_7d | 11 (11) | 0/0/0 | 1848 | 1791 | 1.932 | 0.271 | 0.352 | 307.33 / 31.86 / 7.66 |
| trend_regime | 202 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 702 | 0.919 | 0.358 | 0.359 | 485.20 / 226.95 / 18.22 |
| trend_regime | 303 | next_24h | 80 (80) | 0/0/0 | 1920 | 1874 | 0.972 | 0.275 | 1.467 | 18.87 / 4.43 / 28.44 |
| trend_regime | 303 | next_7d | 11 (11) | 0/0/0 | 1848 | 1803 | 1.931 | 0.283 | 1.394 | 308.63 / 32.54 / 178.99 |
| trend_regime | 303 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 702 | 0.956 | 0.379 | 1.878 | 397.38 / 225.47 / 1103.77 |
| seasonal_ac | 101 | next_24h | 80 (80) | 0/0/0 | 1920 | 1828 | 0.747 | 0.193 | 0.158 | 14.33 / 2.42 / 1.26 |
| seasonal_ac | 101 | next_7d | 11 (11) | 0/0/0 | 1848 | 1764 | 1.360 | 0.197 | 0.158 | 212.53 / 16.28 / 4.50 |
| seasonal_ac | 101 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 684 | 0.695 | 0.182 | 0.189 | 301.30 / 62.57 / 36.56 |
| seasonal_ac | 202 | next_24h | 80 (80) | 0/0/0 | 1920 | 1816 | 0.731 | 0.180 | 0.156 | 14.04 / 2.37 / 1.49 |
| seasonal_ac | 202 | next_7d | 11 (11) | 0/0/0 | 1848 | 1747 | 1.356 | 0.183 | 0.159 | 209.47 / 16.21 / 8.58 |
| seasonal_ac | 202 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 679 | 0.752 | 0.189 | 0.254 | 394.50 / 87.05 / 138.66 |
| seasonal_ac | 303 | next_24h | 80 (80) | 0/0/0 | 1920 | 1818 | 0.729 | 0.177 | 0.158 | 13.87 / 2.23 / 1.15 |
| seasonal_ac | 303 | next_7d | 11 (11) | 0/0/0 | 1848 | 1749 | 1.363 | 0.179 | 0.160 | 210.87 / 14.40 / 5.14 |
| seasonal_ac | 303 | next_calendar_month | 1 (1) | 0/0/0 | 720 | 681 | 0.760 | 0.163 | 0.182 | 340.59 / 57.45 / 23.40 |

### Aggregate per scenario and horizon (hours-weighted MAE over the 3 data seeds)

| Scenario | Horizon | Hours scored (common) | MAE repeat-last-day | MAE baseline | MAE candidate | Candidate better than baseline (runs) |
|---|---|---|---|---|---|---|
| weekly_stable | next_24h | 5575 | 0.700 | 0.120 | 0.114 | 3 of 3 |
| weekly_stable | next_7d | 5366 | 1.351 | 0.118 | 0.113 | 3 of 3 |
| weekly_stable | next_calendar_month | 2084 | 0.699 | 0.120 | 0.116 | 3 of 3 |
| trend_regime | next_24h | 5590 | 0.966 | 0.270 | 1.090 | 0 of 3 |
| trend_regime | next_7d | 5379 | 1.929 | 0.278 | 1.040 | 0 of 3 |
| trend_regime | next_calendar_month | 2095 | 0.913 | 0.375 | 1.302 | 0 of 3 |
| seasonal_ac | next_24h | 5462 | 0.736 | 0.184 | 0.157 | 3 of 3 |
| seasonal_ac | next_7d | 5260 | 1.360 | 0.186 | 0.159 | 3 of 3 |
| seasonal_ac | next_calendar_month | 2044 | 0.736 | 0.178 | 0.208 | 0 of 3 |

Candidate beat the baseline (lower test MAE) in **15 of 27** scenario × seed × horizon cells; the baseline was better or equal in 12.

### Validation selection (candidate mean MAE across horizons on the validation period; frozen before test)

| Scenario | Data seed | hgb-mae-small | hgb-mse-small | hgb-mae-medium | Selected |
|---|---|---|---|---|---|
| weekly_stable | 101 | 0.1037 | 0.1043 | 0.1042 | hgb-mae-small |
| weekly_stable | 202 | 0.1142 | 0.1152 | 0.1147 | hgb-mae-small |
| weekly_stable | 303 | 0.1126 | 0.1129 | 0.1140 | hgb-mae-small |
| trend_regime | 101 | 0.2022 | 0.2047 | 0.2069 | hgb-mae-small |
| trend_regime | 202 | 0.2146 | 0.2162 | 0.2218 | hgb-mae-small |
| trend_regime | 303 | 0.2137 | 0.2086 | 0.2103 | hgb-mse-small |
| seasonal_ac | 101 | 0.3684 | 0.3489 | 0.3415 | hgb-mae-medium |
| seasonal_ac | 202 | 0.4138 | 0.3876 | 0.3904 | hgb-mse-small |
| seasonal_ac | 303 | 0.3599 | 0.3561 | 0.3442 | hgb-mae-medium |

### Timing (this Windows laptop, CPU only)

| Scenario | Data seed | Final training rows | Feature build s | Fit s | Inference ms / origin (24h): r / b / c | Inference ms / origin (month): r / b / c |
|---|---|---|---|---|---|---|
| weekly_stable | 101 | 439629 | 4.183 | 7.084 | 2.8 / 4.3 / 12.3 | 891.0 / 5.7 / 14.3 |
| weekly_stable | 202 | 438825 | 3.627 | 7.286 | 2.3 / 3.6 / 14.9 | 724.3 / 4.7 / 15.0 |
| weekly_stable | 303 | 440865 | 3.546 | 7.276 | 3.4 / 4.8 / 12.8 | 855.6 / 7.2 / 15.6 |
| trend_regime | 101 | 440140 | 4.134 | 6.829 | 4.9 / 7.5 / 22.0 | 1984.0 / 9.7 / 34.2 |
| trend_regime | 202 | 441586 | 9.449 | 10.183 | 5.1 / 7.7 / 24.2 | 2037.1 / 15.5 / 34.8 |
| trend_regime | 303 | 440295 | 8.576 | 3.999 | 5.0 / 7.6 / 22.9 | 2195.7 / 14.5 / 30.8 |
| seasonal_ac | 101 | 431726 | 7.503 | 21.149 | 4.9 / 7.2 / 34.3 | 834.7 / 7.3 / 29.5 |
| seasonal_ac | 202 | 432828 | 4.669 | 3.737 | 3.0 / 4.6 / 12.7 | 1215.2 / 10.6 / 46.2 |
| seasonal_ac | 303 | 431537 | 7.299 | 17.981 | 3.4 / 4.6 / 22.4 | 942.5 / 7.3 / 39.7 |

Suite wall time: 651.4 s.

### Split boundaries (identical rule for every run)

- Series start (first local midnight): 2025-10-05T18:30:00Z
- Train: hours ending at or before 2026-07-12T18:30:00Z
- Validation origins: [2026-07-12T18:30:00Z, 2026-09-20T18:30:00Z); targets before 2026-09-20T18:30:00Z
- Test origins: [2026-09-20T18:30:00Z, 2026-12-09T18:30:00Z); targets before 2026-12-09T18:30:00Z

### Analysis

- **Coverage.** Every method forecast every origin (0 failures) in all 27
  cells, so every origin was eligible. Common scored hours are 95–97 % of the
  expected hours because the synthetic series have 3–5 % missing hours.
  Energy errors are therefore **over common scored hours**, not
  complete-horizon totals.
- **`weekly_stable`:** the candidate is **slightly better** than the
  baseline in 9/9 cells (hours-weighted MAE 0.114 vs 0.120 kWh/h at 24 h;
  0.113 vs 0.118 at 7 d; 0.116 vs 0.120 for the month). That is a small
  gain of about 5 %.
- **`seasonal_ac`:** the candidate is **better at 24 h and 7 d** (0.157 vs
  0.184; 0.159 vs 0.186) but **worse for the calendar month** (0.208 vs
  0.178, 0 of 3). Its month-level energy error is mixed.
- **`trend_regime`:** the candidate is **worse than the baseline in 9/9
  cells**. For data seeds 101 and 303 it fails badly: 24 h MAE about 1.44–1.47
  vs 0.27, worse even than repeat-last-day.
  - **Diagnosed cause** (before the suite finished, on seed 101): after the
    day-330 regime change (night base +0.25 kWh/h), the 90-day night-hour
    profile medians drift into about 0.55–0.65 kWh. During training the
    trees only saw that range for daytime hours, so they predict about
    4 kWh at working-day night hours against actuals of about 0.7.
  - Tree ensembles do not extrapolate, and this feature design makes the
    model split on profile *levels* rather than on the hour.
  - Seed 202 shows milder degradation (0.357 vs 0.266).
- **Repeat-last-day** is the weakest method everywhere at 7 d and month
  (it repeats the last observed day, often a weekend).
- **Validation vs test:**
  - Configuration selection was frozen on validation. For `trend_regime`
    and `seasonal_ac` the validation period (July–September) differs
    materially from the test period (September–December), so validation
    MAE did not predict test behaviour. This is itself a reason for caution.
  - **No design change was made after seeing test results:** the candidate
    and configurations are as fixed before the suite.
- **Timing:**
  - A final fit takes about 4–21 s on about 430–440 k rows, plus 3.5–9.5 s
    of feature building. Suite wall time was 651 s.
  - Candidate inference takes about 12–46 ms per origin.
  - The baseline takes about 4–15 ms.
  - Repeat-last-day's month-horizon timing (0.7–2.2 s) reflects its simple
    backward-search implementation in the offline evaluator, not a
    production path.
- **Overall:** the candidate beat the baseline in **15 of 27** cells, but
  it lost every regime-change cell and **failed catastrophically in 6
  cells**. By robustness, **the P013 baseline remains preferred**.

## 6. Reproduction commands (Windows PowerShell, repo root, existing venv)

```powershell
# one series: generate → validate → evaluate (+ save bundle) → reload & predict
.venv\Scripts\python.exe -m app.training.cli generate --scenario trend_regime --seed 101 --out data\training\trend_regime-101.json
.venv\Scripts\python.exe -m app.training.cli validate --input data\training\trend_regime-101.json
.venv\Scripts\python.exe -m app.training.cli evaluate --input data\training\trend_regime-101.json --seed 0 --report artifacts\reports\trend_regime-101.json --save-bundle artifacts\candidates\trend_regime-101
.venv\Scripts\python.exe -m app.training.cli predict --bundle artifacts\candidates\trend_regime-101 --input data\training\trend_regime-101.json --origin 2026-10-18T18:30:00Z --horizon next_7d --check-reload
# train one config directly (cutoff = day 350) and save a bundle
.venv\Scripts\python.exe -m app.training.cli train --input data\training\trend_regime-101.json --cutoff-days 350 --config hgb-mae-small --seed 0 --out artifacts\candidates\demo
# full suite (3 scenarios x seeds 101/202/303), the numbers in section 5
.venv\Scripts\python.exe -m app.training.cli suite --report artifacts\reports\p016-suite.json
```

- **Linux:** replace `.venv\Scripts\python.exe` with `.venv/bin/python`.
- **Hardware:** no GPU is needed.
- **Git:** `data/` and `artifacts/` are git-ignored; model binaries and
  datasets are never committed.

**Verified locally:**
- `validate` of a malformed file exits 2 (`invalid training input: series_id: Field required`).
- `evaluate --save-bundle` wrote `model.joblib` (376 KB) plus `metadata.json`.
- `predict --check-reload` loaded the bundle twice and returned
  `reload_identical: true` (168 points, 682.009 kWh).

### Bundle metadata (actual `artifacts\candidates\trend_regime-101\metadata.json`, `evaluation` omitted)

```json
{
  "bundle_format": "nexyra-forecast-candidate-bundle-v1",
  "model_id": "hgb-origin-anchored-hgb-mae-small-synthetic-trend_regime-101-2026-09-20T18:30:00Z",
  "model_family": "hgb-origin-anchored",
  "config_name": "hgb-mae-small",
  "params": {
    "loss": "absolute_error",
    "learning_rate": 0.05,
    "max_iter": 200,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 20
  },
  "feature_version": "origin-anchored-v1",
  "feature_names": [
    "local_hour",
    "local_iso_weekday",
    "is_working_day",
    "lead_days",
    "profile_weekday_hour",
    "profile_dayclass_hour",
    "last_obs_same_hour",
    "mean_last_7d",
    "mean_last_28d",
    "support_weekday_hour"
  ],
  "training_cutoff_utc": "2026-09-20T18:30:00Z",
  "timezone": "Asia/Kolkata",
  "working_days_iso": [
    1,
    2,
    3,
    4,
    5
  ],
  "seed": 0,
  "series_id": "synthetic-trend_regime-101",
  "provenance": {
    "synthetic": true,
    "source": "app.training.synthetic",
    "description": "SYNTHETIC generated office load, scenario trend_regime (not measured data)",
    "scenario": "trend_regime",
    "seed": 101
  },
  "training_rows": 440140,
  "fit_seconds": 7.253,
  "feature_build_seconds": 3.099,
  "clip_negative_to_zero": true,
  "min_window_obs": 168,
  "max_lead_hours": 1488,
  "dependency_versions": {
    "python": "3.13.15",
    "scikit-learn": "1.9.1",
    "numpy": "2.5.3",
    "joblib": "1.6.0"
  },
  "created_utc": "2026-09-24T15:47:02Z",
  "model_sha256": "8168df03c1c23d645b5f8e59d4e87f1f8eda18ee4a312d0f7245ce40813e3324",
  "status": "offline candidate — NOT deployed; not loaded by /v1/forecast; model_available stays false"
}
```

**Security note:** loading a bundle executes joblib/pickle code. Only load
bundles you generated locally with this workflow; never load uploaded model
files. `load_bundle` checks the bundle format, the feature version and the
recorded SHA-256, which guards against accidental corruption but not against
a malicious file.

## 7. Production boundary

- **Unchanged production code:** `app/main.py`, `app/forecast/{models,validate,baseline,service}.py`
  and `app/analysis/*` are unchanged.
  - `/v1/analyze` and `/v1/forecast` behave exactly as before (all 37 analyze
    and 37 forecast tests pass).
  - `app/training` is never imported by the app.
- **The only change under `app/forecast`** is the offline evaluation helper
  (`evaluation.py`): labels plus `expected_hours`. It is not on the request
  path.
- **Model availability:** still `false`, and `model_version` is still
  `null`. The candidate is not loaded anywhere.

## 8. Verification

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **103 passed**: 21 new training tests plus 82 existing, including all analysis/forecast regressions. The 1 warning is Starlette's existing httpx notice. |
| `.venv\Scripts\python.exe -m pip check` | No broken requirements found |
| `.venv\Scripts\python.exe scripts\check_env.py` | Python 3.13.15 venv, imports OK |
| `node scripts/verify-contract.mjs` | 75 passed, 0 failed |

No HTTP checks were repeated, because the production request path did not
change. No service was started.

**New tests** (`tests/test_training.py`, 21):
- input rejection (10 cases);
- deduplication and missing-hours-stay-missing;
- NaN rejection;
- NaN (not 0) features for missing history;
- future-data leakage (features and training);
- the minimum-history failure;
- determinism with a fixed seed;
- save/reload equivalence plus tamper and feature-version refusal;
- split and window boundaries;
- selection frozen before the test;
- shared scored timestamps and failure exclusion;
- the CLI generate/validate round trip.

## 9. Limitations

- **Synthetic data only.** The scenarios encode assumptions (a weekly
  pattern, a specific trend/regime/season), and no real or simulator export
  was evaluated.
- **One temporal split per series.** There is no rolling-origin
  cross-validation, and only one month-horizon origin per window.
- **The candidate's features rely on history medians,** so tree models
  cannot extrapolate beyond the training ranges (see the failure analysis).
- **Bundles use pickle** (local trust only).

## 10. Recommendation and integration proposal

**Should the candidate be integrated?** **Not now.** Keep the P013
statistical baseline as the production forecaster (no change). The candidate
gives small gains on stable or seasonal patterns at short horizons, but it
is not robust: it fails badly under a regime change, and it is worse for the
calendar-month horizon on the seasonal pattern.

**Next steps (a future assignment, no automatic promotion):**
1. **Redesign for robustness.** Pre-registered before any new evaluation:
   - predict the **residual or ratio relative to the baseline profile**
     (`y − profile_weekday_hour`), so the baseline is the fallback and trees
     only learn corrections;
   - add level-normalised features (value ÷ mean_last_28d);
   - consider clipping corrections.
2. **Evaluate on fresh data.** Use new seeds (for example 404/505/606, never
   used for design) and **rolling-origin** splits, plus new regime/holiday
   scenarios. Keep the same identical-timestamp scoring.
3. **Add real evidence.** Once simulator history/export and the auditor
   export exist, evaluate on real exports (non-synthetic provenance) with a
   temporal holdout from a later period than any design work.
4. **Promotion criteria**, proposed and to be agreed beforehand:
   - lower MAE than the baseline on every scenario and horizon on fresh
     holdouts;
   - no cell worse than the baseline by more than 10 %;
   - no failure modes.
   Only then design API integration, e.g. `model: {"version": ...}`
   selection with the baseline as the default and fallback, a loaded bundle
   verified at startup, and `model_available: true` with a non-null
   `model_version`, under a separate reviewed task.
