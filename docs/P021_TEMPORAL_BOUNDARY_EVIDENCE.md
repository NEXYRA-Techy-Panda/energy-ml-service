# P021_TEMPORAL_BOUNDARY_EVIDENCE — P016 temporal evaluation correctness (M2-R1)

Agent B — Claude Code | P021 | M2-R1. Owner Mohan. Date 2026-09-24. Scope:
`energy-ml-service` only. Implementation is **completed**; review is
**pending**. The commit hash is reported in the P021 return report after the
push.

- **Review position going in:** P016 offline implementation accepted based
  on supplied evidence; candidate **not** approved for production; temporal
  correctness pending this check.
- **Not part of this task:** tuning, a replacement model, or promotion. P013
  remains the production baseline.

## Result: no boundary defect

The audit traced the **actual examples** used in each phase and checked
**target intervals**, not only origins. Every invariant holds for every
horizon, including next-calendar-month forecasts whose month could cross a
split date. **No fix to example selection or scoring was needed**, and no P016
metric changes.

### Source locations (the mechanisms that enforce the boundaries)

| Invariant | Mechanism |
|---|---|
| Initial fit / final refit use no target ending after their cutoff | `app/training/candidate.py` `build_training_rows`: for each origin the lead loop `break`s when `t + 1 h > cutoff`, so long-horizon leads from origins before the cutoff are **truncated**, not kept; a missing target makes no row. `train(series, cutoff, …)` fits only on these rows. |
| Validation/selection and test use only full horizons inside their window | `app/training/evaluate.py` `eval_origins`: an origin is kept only if `horizon_bounds(horizon, o, tz).end <= b` (window end). A month whose end crosses the window end is excluded, not partially scored. |
| Selection sees only validation | `evaluate.py` `run_experiment`: each config is trained with cutoff `train_end` and scored on `[train_end, validation_end)`. The choice is frozen (`selection`) before `train(…, validation_end, …)` and the single test `evaluate_window(…, validation_end, test_end, …)`. |
| Features use only observations available at the origin | `app/training/features.py` `SortedHistory.window`: `bisect_right(times, origin − 1 h)`, i.e. observations ending at or before the origin (latest ≤ 2,160). Baseline and repeat-last-day use `app/forecast/evaluation.py` `visible_history` (`t + 1 h <= cutoff`). |
| Test does not treat unavailable targets as observed | `evaluate_window` scores only `actual = {t: history[t] for t in hours if t in history}` intersected with every method's predictions (common scored hours). Missing hours are never scored or filled. |

The only code change in P021 is **audit instrumentation**: an optional
`trace` parameter on `build_training_rows`, `train`, `evaluate_window`
and `run_experiment`. It defaults to `None` and does not change behaviour.
The traced run reproduces P016's validation scores exactly (see below).

## Boundary table (actual trace; synthetic-trend_regime-101, SYNTHETIC; selected config hgb-mae-small)

**Split timestamps (UTC):**
- series start (local midnight): 2025-10-05T18:30:00Z;
- **train cutoff** 2026-07-12T18:30:00Z;
- **test begins** 2026-09-20T18:30:00Z;
- test end 2026-12-09T18:30:00Z.

### A / C — model fitting (rows = (origin, target hour) examples)

| Phase | Origins (earliest → latest, count) | Target starts (earliest → latest) | Latest target END | Cutoff | Examples | Invariant |
|---|---|---|---|---|---|---|
| A. Initial fit (each config) | 2025-10-19T18:30:00Z → 2026-07-11T18:30:00Z (266) | 2025-10-19T18:30:00Z → 2026-07-12T17:30:00Z | **2026-07-12T18:30:00Z** | 2026-07-12T18:30:00Z | 338894 rows (lead <24 h 6176; 24 h–7 d 36563; ≥7 d 296155; max lead 1487 h) | yes |
| C. Final refit | 2025-10-19T18:30:00Z → 2026-09-19T18:30:00Z (336) | 2025-10-19T18:30:00Z → 2026-09-20T17:30:00Z | **2026-09-20T18:30:00Z** | 2026-09-20T18:30:00Z | 440140 rows (lead <24 h 7809; 24 h–7 d 46361; ≥7 d 385970; max lead 1487 h) | yes |

- **A:** the rows are identical for all three configs (yes).
- **A (crossing origins):** 61 training origins lie within 62 days
  before the cutoff, i.e. their month-scale lead window crosses it. They
  contributed 43907 rows, **all with targets ending at or before the cutoff**.
- **C:** 61 such origins contributed 43949 rows, all ending by test start.

### B / D — scoring (origins must have their FULL horizon inside the window)

| Phase | Horizon | Origins (earliest → latest, count) | Scored target starts (earliest → latest) | Latest full-horizon END (latest scored END) | Window end (cutoff) | Scored targets | Invariants |
|---|---|---|---|---|---|---|---|
| B. Validation + selection | next_24h | 2026-07-12T18:30:00Z → 2026-09-19T18:30:00Z (70, eligible 70) | 2026-07-12T18:30:00Z → 2026-09-20T17:30:00Z | **2026-09-20T18:30:00Z** (scored 2026-09-20T18:30:00Z) | 2026-09-20T18:30:00Z | 1633 | yes |
| B. Validation + selection | next_7d | 2026-07-12T18:30:00Z → 2026-09-13T18:30:00Z (10, eligible 10) | 2026-07-12T18:30:00Z → 2026-09-20T17:30:00Z | **2026-09-20T18:30:00Z** (scored 2026-09-20T18:30:00Z) | 2026-09-20T18:30:00Z | 1633 | yes |
| B. Validation + selection | next_calendar_month | 2026-07-14T18:30:00Z → 2026-07-14T18:30:00Z (1, eligible 1) | 2026-07-31T18:30:00Z → 2026-08-31T17:30:00Z | **2026-08-31T18:30:00Z** (scored 2026-08-31T18:30:00Z) | 2026-09-20T18:30:00Z | 718 | yes |
| D. Final test | next_24h | 2026-09-20T18:30:00Z → 2026-12-08T18:30:00Z (80, eligible 80) | 2026-09-20T19:30:00Z → 2026-12-09T17:30:00Z | **2026-12-09T18:30:00Z** (scored 2026-12-09T18:30:00Z) | 2026-12-09T18:30:00Z | 1857 | yes |
| D. Final test | next_7d | 2026-09-20T18:30:00Z → 2026-11-29T18:30:00Z (11, eligible 11) | 2026-09-20T19:30:00Z → 2026-12-06T17:30:00Z | **2026-12-06T18:30:00Z** (scored 2026-12-06T18:30:00Z) | 2026-12-09T18:30:00Z | 1785 | yes |
| D. Final test | next_calendar_month | 2026-10-14T18:30:00Z → 2026-10-14T18:30:00Z (1, eligible 1) | 2026-10-31T18:30:00Z → 2026-11-30T17:30:00Z | **2026-11-30T18:30:00Z** (scored 2026-11-30T18:30:00Z) | 2026-12-09T18:30:00Z | 691 | yes |

- **B:** origins and scored targets are identical for every config (yes).
- **B selection inputs** (mean validation MAE):
  hgb-mae-small 0.2022; hgb-mse-small 0.2047; hgb-mae-medium 0.2069.
  These are identical to the P016 suite's validation table for this series,
  so tracing did not change behaviour.
- **Month origins excluded because their month would cross the window end:**
  - validation: origin 2026-08-14T18:30:00Z, month ends 2026-09-30T18:30:00Z > 2026-09-20T18:30:00Z
  - validation: origin 2026-09-14T18:30:00Z, month ends 2026-10-31T18:30:00Z > 2026-09-20T18:30:00Z
  - test: origin 2026-11-14T18:30:00Z, month ends 2026-12-31T18:30:00Z > 2026-12-09T18:30:00Z
- **Feature windows:** end at or before the origin for all 416 traced
  origins (yes).
- **Test scoring:** all scored test targets were observed hours (yes).
- **All invariants hold:** yes.

**Required invariants (P021):**
- **Initial fit:** no target ends after the training cutoff. The latest END
  is 2026-07-12T18:30:00Z, which equals the cutoff.
- **Configuration selection:** no target ends after test begins. The latest
  validation END is 2026-09-20T18:30:00Z, which
  equals test start.
- **Final refit:** no target ends after test begins. The latest END is
  2026-09-20T18:30:00Z.
- **Features:** use only observations available at their origin.
- **Test forecasts:** do not treat unavailable targets as observed.

Later rolling test origins do use observations that have become available by
each origin, as documented in P016. They never affect configuration, which is
frozen before any test forecast.

Reproduce (about 2 minutes; writes `artifacts/reports/p021-boundary-audit.json`, git-ignored):

```powershell
.venv\Scripts\python.exe scripts\audit_temporal_boundaries.py --scenario trend_regime --seed 101
```

The boundaries are data-independent apart from which hours are missing:
every scenario and seed uses the same split rule and origin grid.

## Regression tests added (`tests/test_training.py`)

- `test_training_origins_before_the_cutoff_never_contribute_targets_after_it`:
  covers a training origin before the cutoff whose month-scale targets extend
  past it. Rows are truncated at the cutoff, and no traced target ends after
  it.
- `test_month_origin_whose_month_crosses_the_window_end_is_excluded_from_scoring`:
  - a Nov-15 origin whose December crosses the window end is excluded;
  - an Oct-15 origin whose November ends exactly at the window end is kept;
  - the traced horizon ends and scored targets all stay at or before the
    window end.
- `test_test_period_outcomes_cannot_change_configuration_selection`: runs
  the real `run_experiment` on a shortened split (train ≤ day 60,
  validation to day 110, tiny models) twice, once with every test-period
  observation replaced by 10⁶. The results:
  - validation selection scores, the frozen choice, and every
    initial-fit/refit example are **identical**;
  - only the test scores change;
  - the Dec-15 validation origin, whose January would cross test start, is
    never scored for the month horizon (it is used for the 24 h horizon,
    which fits).
- **Already present (P016):** changing observations beyond the training
  cutoff cannot alter the initial fit
  (`test_training_ignores_everything_after_the_cutoff`), and future
  observations cannot alter features at month-scale leads.

## Verification

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **106 passed**: 24 training tests (3 new) plus 82 analysis/forecast/app regressions. The 1 warning is Starlette's httpx notice. |
| `.venv\Scripts\python.exe -m pip check` | No broken requirements found |
| `.venv\Scripts\python.exe scripts\check_env.py` | Python 3.13.15 venv, imports OK |
| `node scripts/verify-contract.mjs` | 75 passed, 0 failed (shared contract unchanged) |
| `scripts/audit_temporal_boundaries.py` (trend_regime, seed 101) | all invariants hold |

- **No reruns:** the 651-second P016 suite was **not** rerun, because no
  boundary defect exists and no reported number changes.
- **No services:** no HTTP checks and no services were started (offline-only
  change).
- **Production unchanged:** `app/main.py`, `app/forecast/*` and
  `app/analysis/*` are unchanged. `/v1/analyze` and `/v1/forecast`
  behave as before, and `model_available` stays `false`.

## Status of earlier metrics

- **P016 results remain valid as reported.** Initial fits, validation
  selection and final refits never used a target from the test period.
- The P016 test outcomes had **already been inspected** (during the P016
  failure analysis). They remain a diagnostic evaluation, **not** an
  untouched confirmation set. Any future promotion needs new held-out data.

## Promotion policy clarification

The P016 statement "better on every scenario and horizon, and no case more
than 10 % worse" was an **agent proposal**, not an agreed acceptance gate. No
trained-model promotion is authorised. The candidate remains
offline-only, and the P013 baseline remains production.
