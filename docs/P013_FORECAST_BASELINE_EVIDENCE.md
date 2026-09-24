# P013_FORECAST_BASELINE_EVIDENCE — hourly forecasting baseline (M1)

Agent B — Claude Code | P013 | M1. Owner Mohan. Date 2026-09-24. Scope:
`energy-ml-service` only. Implementation is **completed**; review is
**pending**. The commit hash is reported in the P013 return report after the
push.

## Starting state

- No `AGENTS.md`. `main` was at `36f5832` (P010, accepted based on evidence
  as a deterministic rule foundation), equal to `origin/main`, with a clean
  tree.
- Contract 1.0.1 is unchanged (`node scripts/verify-contract.mjs`: 75/75).
- There are no new dependencies. The baseline uses the Python standard
  library (`statistics.median`, `zoneinfo`) plus the already pinned `tzdata`.

## Interface (frozen from contract API.md Example B + CONTRACT.md §8)

`POST /v1/forecast`, called only by auditor-backend.

- **Request (Example B fields):**
  - `contract_version` (`"1.0.1"`), `dataset_id`, `origin_utc`;
  - `horizon` (`next_24h` | `next_7d` | `next_calendar_month`);
  - `history_hourly_kwh[{start_utc, energy_kwh}]` (≤ 2,160 points);
  - `calendar{timezone, working_days_iso, open_local, close_local}`;
  - `future_assumptions{schedule, environment}`;
  - `model{version}`.
- **Response (contract fields):** `horizon`, `origin_utc`, `model_version`,
  `points[{start_utc, energy_kwh}]`, `uncertainty: "unavailable"`.

### Local API clarifications (smallest necessary; shared contract not edited)

1. **Hourly grid.** Forecast points are `origin_utc + k·1 h`.
   - `origin_utc` must be a full hour **in UTC** (`HH:00:00Z`, as in Example
     B) **or on the calendar timezone's local clock** (Asia/Kolkata:
     `HH:30:00Z`).
   - Every history point must be one **complete** hour on the same grid.
   - Partial hours are not accepted, and nothing is resampled.
2. **`next_calendar_month`** needs the grid to line up with local midnight,
   i.e. an origin on the local clock (Asia/Kolkata `HH:30:00Z`). Otherwise
   the month boundaries (local 00:00 = `18:30Z`) would fall mid-hour. A
   UTC-aligned origin gets 400 with an explanation.
3. **Timezone.** Only `Asia/Kolkata` is accepted (CONTRACT.md §1: the only v1
   building timezone). DST-observing zones get 400. Nothing is assumed when
   the timezone is missing (400).
4. **Optional fields:**
   - `calendar.overnight` is optional; if given, it must equal
     `close_local < open_local`, and `open_local == close_local` is rejected.
   - `future_assumptions` and `model` are optional.
   - `model.version`, if given, must equal the baseline version
     `hourly-profile-median-v1`. The contract's illustrative `"baseline-v1"`
     names no model that exists here, so it gets 400 with the valid value.
5. **Model and uncertainty fields.**
   - `model_version` is **`null`** (no trained model).
   - `baseline_version: "hourly-profile-median-v1"` is added, and the same
     value is reported by `GET /v1/model/info` (`baseline_version`).
   - `model_available` stays `false`.
   - The baseline forecasts without a model, so it does **not** return
     `MODEL_UNAVAILABLE`. API.md's note ("forecast calls then return
     MODEL_UNAVAILABLE") applies to model-based forecasts; this is the same
     clarification P010 made for rule-based analysis.
6. **`INSUFFICIENT_DATA`** is returned with **HTTP 422** (the contract names
   the code, not the status).
7. **Cost.** The Python forecast interface has **no tariff or cost field**
   (Example B), so none is computed. Unknown fields such as
   `tariff_inr_per_kwh` get 400. Energy is therefore tariff-independent by
   construction; costing belongs to auditor-backend.
8. **Response additions:** `baseline_version`, `method`, `timezone`,
   `horizon_start_utc`/`horizon_end_utc`, per-point `basis`/`support`,
   `total_energy_kwh`, `history_coverage`, `basis_counts`, `assumptions`,
   `assumptions_recorded`, `limitations`, `warnings`.

## Validation

In order:
1. Body size ≤ 2 MiB, else 413.
2. JSON, with NaN/Infinity rejected (400).
3. `contract_version` (`UNSUPPORTED_VERSION`).
4. **More than 2,160 history points → 413 `REQUEST_TOO_LARGE`.**
5. Forbidden fault-label fields anywhere → 400.
6. Closed strict models (unknown fields, bounds, patterns, finite
   non-negative energy, known horizon).
7. Semantics:
   - supported timezone; calendar consistency; model version;
   - origin alignment; history on the grid;
   - **no observation ending after the origin** (future observations → 400);
   - ascending order;
   - **identical duplicates deduplicated and disclosed; conflicting
     duplicates → 400.**

Missing hours are **gaps**: never zero, and they never count toward
eligibility.

## Baseline computation (`hourly-profile-median-v1`, method `statistical_baseline`)

For each forecast hour, the value is the **median** of observed history
hours at the first level with enough support:

| Level (`basis`) | Group | Min. observations |
|---|---|---|
| `weekday_hour` | same local ISO weekday + local hour | 2 |
| `day_class_hour` | same working/non-working class (from `working_days_iso`) + local hour | 3 |
| `hour_of_day` | same local hour, any day (disclosed fallback) | 3 |

- The **median** was chosen because it is robust to single anomalous hours
  in small histories.
- Levels 2 and 3 are disclosed with `FALLBACK_DAY_CLASS` /
  `FALLBACK_HOUR_OF_DAY` warnings.
- Each point reports its `basis` and `support` (number of observations).
- `total_energy_kwh` is the unrounded sum of the points.
- The same input gives the same output.

**Eligibility** (fixed before implementation, in `app/forecast/constants.py`):
- at least **168 / 336 / 672 observed hours** for next_24h / next_7d /
  next_calendar_month;
- **and** every horizon hour must be resolvable by the hierarchy.

Otherwise the service returns **422 `INSUFFICIENT_DATA`**, stating the
missing requirement or the unsupported local weekday/hour slots. The
two-minute contract fixture (0.03 kWh) is far below eligibility and is
rejected.

**Other warnings:**
- `MISSING_HOURS`: gaps inside the history span;
- `DUPLICATES_DEDUPED`;
- `STALE_HISTORY`: the last observation ends more than 7 days before the
  origin;
- `GAP_BEFORE_HORIZON`: hours between the origin and the next month are not
  forecast, and no observations are invented for them;
- `INPUTS_NOT_USED`: always present.

### Inputs accepted but not influencing the baseline

These are listed in `INPUTS_NOT_USED` and echoed in `assumptions_recorded`:
- `calendar.open_local`, `calendar.close_local` (and `overnight`);
- `future_assumptions.schedule`;
- `future_assumptions.environment`.

Only the observed hourly history plus `calendar.timezone` and
`working_days_iso` influence the result. No weather, occupancy or
policy-savings sensitivity is claimed; a test confirms different
environment/schedule assumptions give identical points.

## Timezone and calendar semantics

- **Local classification:** the weekday, hour and day class of every hour
  are taken from its **local** start time in Asia/Kolkata (UTC+05:30, no
  DST). For example, `2026-01-04T20:00Z` (Sunday UTC) is Monday 01:30 IST, a
  working day.
- **Horizons:**
  - `next_24h` = [origin, origin + 24 h), 24 points;
  - `next_7d` = [origin, origin + 7 d), 168 points;
  - `next_calendar_month` = the **complete local calendar month after the
    month containing the origin** (local 00:00 on day 1 inclusive → local
    00:00 on day 1 of the following month exclusive). It is **not** "next 30
    days". Points = days × 24: January 744, February 672 (696 in leap years),
    30-day months 720.
- **Tested month cases:**
  - Dec → Jan year rollover (`2026-12-31T18:30Z`–`2027-01-31T18:30Z`);
  - non-leap Feb 2027 (672);
  - leap Feb 2028 (696);
  - an origin that is Jan 31 in UTC but Feb 1 locally → March.

## Evaluation (offline, chronological holdout; not on the request path)

- **Code:** `app/forecast/evaluation.py` and
  `scripts/evaluate_forecast_baseline.py`.
- **No future leakage:** for each cutoff, only observations ending at or
  before the cutoff are visible, limited to the latest 2,160 as in
  production. The following horizon's observed hours are the withheld truth.
  A test replaces all post-cutoff values with 1e6: the predictions do not
  change, only the scores against the poisoned truth.
- **Compared methods:** the baseline versus **repeat-last-day** (each hour
  takes the value from the last visible observed day at the same time), on
  identical hours.
- **Metrics:** MAE (kWh per hour) and the energy error over common scored
  hours per origin (predicted − actual summed over hours that every method
  predicted and that were observed; kWh). No percentages.
- **Data provenance: SYNTHETIC.**
  - Data is generated by `app/forecast/synthetic.py`: base 0.45 kWh/h, plus
    5.0 during working hours, a Monday +0.4 and a 13:00 −1.5, with ±8 %
    noise and 5 % missing hours.
  - 150 days from 2026-10-05 local, with a reporting seed of 20260924 that
    no test uses.
  - Baseline parameters were fixed beforehand and **not tuned on these
    results**.
  - **These numbers describe synthetic data only, not real-building
    accuracy.** The generator's weekly pattern matches the baseline's
    structural assumption, so it favours the baseline. Real data (holidays,
    events, seasonal change) will be harder.

> **Label correction (P016, 2026-09-24).** The error originally labelled
> "mean abs aggregate error / origin" (and called "total energy per forecast"
> in the P013 return report) is the energy error over **common scored hours**
> only: hours that were observed and predicted by both methods. Because 5 % of
> the synthetic hours are missing, only 639 of 672 expected hours (24 h, 7 d)
> and 1,343 of 1,416 (month) were scored, so it is **not** a complete-horizon
> total error. The calculation is unchanged and the numbers are identical; the
> output now reports expected and scored hours.

Measured output (`.venv\Scripts\python.exe scripts\evaluate_forecast_baseline.py`, relabelled in P016):

```json
{
  "data": "SYNTHETIC generated office load (not measured data)",
  "seed": 20260924,
  "baseline_version": "hourly-profile-median-v1",
  "history_hours_generated": 3404,
  "horizons": {
    "next_24h": {
      "origins": 28,
      "hours_expected": 672,
      "hours_scored_common": 639,
      "baseline": {
        "mae_kwh_per_hour": 0.1223,
        "energy_error_over_common_scored_hours_kwh": {
          "mean_abs_per_origin": 0.791,
          "mean_per_origin": -0.063
        }
      },
      "repeat_last_day": {
        "mae_kwh_per_hour": 0.7018,
        "energy_error_over_common_scored_hours_kwh": {
          "mean_abs_per_origin": 13.635,
          "mean_per_origin": -0.006
        }
      }
    },
    "next_7d": {
      "origins": 4,
      "hours_expected": 672,
      "hours_scored_common": 639,
      "baseline": {
        "mae_kwh_per_hour": 0.1218,
        "energy_error_over_common_scored_hours_kwh": {
          "mean_abs_per_origin": 1.117,
          "mean_per_origin": -0.429
        }
      },
      "repeat_last_day": {
        "mae_kwh_per_hour": 1.3702,
        "energy_error_over_common_scored_hours_kwh": {
          "mean_abs_per_origin": 214.833,
          "mean_per_origin": -214.833
        }
      }
    },
    "next_calendar_month": {
      "origins": 2,
      "hours_expected": 1416,
      "hours_scored_common": 1343,
      "baseline": {
        "mae_kwh_per_hour": 0.1239,
        "energy_error_over_common_scored_hours_kwh": {
          "mean_abs_per_origin": 2.364,
          "mean_per_origin": 0.648
        }
      },
      "repeat_last_day": {
        "mae_kwh_per_hour": 0.7765,
        "energy_error_over_common_scored_hours_kwh": {
          "mean_abs_per_origin": 320.639,
          "mean_per_origin": 320.639
        }
      }
    }
  }
}
```

| Horizon (origins) | Hours expected | Common hours scored | Baseline MAE kWh/h | Repeat-last-day MAE kWh/h | Baseline mean abs energy error over common scored hours / origin | Repeat-last-day mean abs energy error over common scored hours / origin |
|---|---|---|---|---|---|---|
| next_24h (28) | 672 | 639 | 0.1223 | 0.7018 | 0.791 kWh | 13.635 kWh |
| next_7d (4) | 672 | 639 | 0.1218 | 1.3702 | 1.117 kWh | 214.833 kWh |
| next_calendar_month (2) | 1416 | 1343 | 0.1239 | 0.7765 | 2.364 kWh | 320.639 kWh |

- **next_7d and month:** repeat-last-day is weak here because it repeats the
  last observed day (a weekend day for Monday cutoffs) across working days.
  That is an inherent property of that naive method, not a tuning choice.

## Checks (2026-09-24)

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **82 passed**. The 1 warning is Starlette's existing httpx→httpx2 notice. |
| `.venv\Scripts\python.exe -m pip check` | No broken requirements found |
| `.venv\Scripts\python.exe scripts\check_env.py` | Python 3.13.15 venv, imports OK |
| `node scripts/verify-contract.mjs` | 75 passed, 0 failed |

The new tests (`tests/test_forecast.py`, 37 cases; small in-memory synthetic
histories) cover:
- **Consistency and patterns:**
  - constant input: consistent points and totals (24 → 30.0 kWh,
    168 → 210.0 kWh);
  - a known weekday/hour pattern is preserved exactly;
  - fallbacks are disclosed (day-class, hour-of-day).
- **Missing data and eligibility:**
  - missing hours are not zeros: 80 % missing still gives 2.0, and gaps
    don't count toward eligibility;
  - insufficient history: 168/672-hour minimums and an unobserved 02:00
    slot give 422;
  - fixture-scale history gives 422;
  - 2,161 points give 413 (2,160 accepted).
- **Rejected inputs:** future observations, off-grid points, negative
  energy, out-of-order points, a misaligned origin, an unknown horizon, an
  unsupported version, a missing timezone, duplicate weekdays, open == close,
  an unknown model version, a tariff field, and fault fields all give 400
  with the exact field. NaN gives 400. Identical duplicates are deduplicated
  and conflicting ones give 400.
- **Determinism:** identical output for identical input.
- **Horizons:** next_24h and next_7d boundaries and counts, and the Example-B
  UTC-hour grid.
- **Calendar and timezone:**
  - next_calendar_month: year rollover, non-leap and leap February, and a
    UTC/local month boundary;
  - a UTC-aligned origin for a month forecast gives 400;
  - Asia/Kolkata local weekday/hour/day class;
  - a DST-observing timezone gives 400.
- **Recorded assumptions:** accepted but do not change the forecast.
- **Holdout:** no future leakage, and a like-for-like comparison.
- **P010 regression:** all 37 `/v1/analyze` tests are unchanged and pass.
  The model-info test now expects the baseline version, and the stale
  "forecast 404" check was replaced by a "route exists" check.

## Live HTTP evidence (port 8000)

- **Start command:** `.venv\Scripts\python.exe -m app`, with launcher PID
  21928 and interpreter PID 15856, bound to 127.0.0.1:8000.
- **Data:** synthetic only.

- `GET /health` → 200
  `{"data":{"status":"ok","model_available":false},"meta":{"request_id":"7be6f49e-101f-4451-9eda-4a7ba9d870e4"}}`
- `GET /v1/model/info` → 200
  `{"data":{"model_available":false,"model_version":null,"baseline_version":"hourly-profile-median-v1","contract_version":"1.0.1"},"meta":{"request_id":"9e9a9f80-3a6f-4f6f-8051-5db2da9275c4"}}`
- `POST /v1/forecast` with only the last 72 hours of the request below → 422
  `{"error":{"code":"INSUFFICIENT_DATA","message":"next_24h requires at least 168 observed history hours (7 days); got 72. Missing hours are not treated as zero.","field":"history_hourly_kwh"}}`
- `POST /v1/analyze` with the P010 fixture request → 200 with one
  `light-a` finding (0.01 kWh avoidable) and `fridge-b` excluded (regression
  check).

Both PIDs were stopped afterwards and port 8000 was free. **No process is
left running.**

### Complete request — `POST http://localhost:8000/v1/forecast` (SYNTHETIC, seed 4242, 7 days)

```json
{
  "contract_version": "1.0.1",
  "dataset_id": "ds-synthetic-demo",
  "origin_utc": "2027-01-03T18:30:00Z",
  "horizon": "next_24h",
  "history_hourly_kwh": [
    {"start_utc":"2026-12-27T18:30:00Z","energy_kwh":0.4742},
    {"start_utc":"2026-12-27T19:30:00Z","energy_kwh":0.4216},
    {"start_utc":"2026-12-27T20:30:00Z","energy_kwh":0.4401},
    {"start_utc":"2026-12-27T21:30:00Z","energy_kwh":0.4708},
    {"start_utc":"2026-12-27T22:30:00Z","energy_kwh":0.4758},
    {"start_utc":"2026-12-27T23:30:00Z","energy_kwh":0.4893},
    {"start_utc":"2026-12-28T00:30:00Z","energy_kwh":0.4639},
    {"start_utc":"2026-12-28T01:30:00Z","energy_kwh":0.4642},
    {"start_utc":"2026-12-28T02:30:00Z","energy_kwh":0.4542},
    {"start_utc":"2026-12-28T03:30:00Z","energy_kwh":6.5627},
    {"start_utc":"2026-12-28T04:30:00Z","energy_kwh":4.8764},
    {"start_utc":"2026-12-28T05:30:00Z","energy_kwh":6.1966},
    {"start_utc":"2026-12-28T06:30:00Z","energy_kwh":6.0582},
    {"start_utc":"2026-12-28T07:30:00Z","energy_kwh":4.6244},
    {"start_utc":"2026-12-28T08:30:00Z","energy_kwh":5.6775},
    {"start_utc":"2026-12-28T09:30:00Z","energy_kwh":6.2118},
    {"start_utc":"2026-12-28T10:30:00Z","energy_kwh":5.3478},
    {"start_utc":"2026-12-28T11:30:00Z","energy_kwh":5.8978},
    {"start_utc":"2026-12-28T12:30:00Z","energy_kwh":0.4284},
    {"start_utc":"2026-12-28T13:30:00Z","energy_kwh":0.453},
    {"start_utc":"2026-12-28T14:30:00Z","energy_kwh":0.3698},
    {"start_utc":"2026-12-28T15:30:00Z","energy_kwh":0.4598},
    {"start_utc":"2026-12-28T16:30:00Z","energy_kwh":0.4748},
    {"start_utc":"2026-12-28T17:30:00Z","energy_kwh":0.4028},
    {"start_utc":"2026-12-28T18:30:00Z","energy_kwh":0.4581},
    {"start_utc":"2026-12-28T19:30:00Z","energy_kwh":0.4995},
    {"start_utc":"2026-12-28T20:30:00Z","energy_kwh":0.4548},
    {"start_utc":"2026-12-28T21:30:00Z","energy_kwh":0.4768},
    {"start_utc":"2026-12-28T22:30:00Z","energy_kwh":0.4767},
    {"start_utc":"2026-12-28T23:30:00Z","energy_kwh":0.4657},
    {"start_utc":"2026-12-29T00:30:00Z","energy_kwh":0.4538},
    {"start_utc":"2026-12-29T01:30:00Z","energy_kwh":0.4528},
    {"start_utc":"2026-12-29T02:30:00Z","energy_kwh":0.4113},
    {"start_utc":"2026-12-29T03:30:00Z","energy_kwh":5.1225},
    {"start_utc":"2026-12-29T04:30:00Z","energy_kwh":5.6545},
    {"start_utc":"2026-12-29T05:30:00Z","energy_kwh":4.9901},
    {"start_utc":"2026-12-29T06:30:00Z","energy_kwh":5.4783},
    {"start_utc":"2026-12-29T07:30:00Z","energy_kwh":4.519},
    {"start_utc":"2026-12-29T08:30:00Z","energy_kwh":5.9648},
    {"start_utc":"2026-12-29T09:30:00Z","energy_kwh":5.4024},
    {"start_utc":"2026-12-29T10:30:00Z","energy_kwh":4.3648},
    {"start_utc":"2026-12-29T11:30:00Z","energy_kwh":5.5562},
    {"start_utc":"2026-12-29T12:30:00Z","energy_kwh":0.4372},
    {"start_utc":"2026-12-29T13:30:00Z","energy_kwh":0.4925},
    {"start_utc":"2026-12-29T14:30:00Z","energy_kwh":0.5282},
    {"start_utc":"2026-12-29T15:30:00Z","energy_kwh":0.4626},
    {"start_utc":"2026-12-29T16:30:00Z","energy_kwh":0.426},
    {"start_utc":"2026-12-29T17:30:00Z","energy_kwh":0.4553},
    {"start_utc":"2026-12-29T18:30:00Z","energy_kwh":0.4404},
    {"start_utc":"2026-12-29T19:30:00Z","energy_kwh":0.4723},
    {"start_utc":"2026-12-29T20:30:00Z","energy_kwh":0.3922},
    {"start_utc":"2026-12-29T21:30:00Z","energy_kwh":0.398},
    {"start_utc":"2026-12-29T22:30:00Z","energy_kwh":0.4658},
    {"start_utc":"2026-12-29T23:30:00Z","energy_kwh":0.4467},
    {"start_utc":"2026-12-30T00:30:00Z","energy_kwh":0.4327},
    {"start_utc":"2026-12-30T01:30:00Z","energy_kwh":0.4407},
    {"start_utc":"2026-12-30T02:30:00Z","energy_kwh":0.4384},
    {"start_utc":"2026-12-30T03:30:00Z","energy_kwh":5.5942},
    {"start_utc":"2026-12-30T04:30:00Z","energy_kwh":5.4076},
    {"start_utc":"2026-12-30T05:30:00Z","energy_kwh":5.7382},
    {"start_utc":"2026-12-30T06:30:00Z","energy_kwh":5.723},
    {"start_utc":"2026-12-30T07:30:00Z","energy_kwh":3.6103},
    {"start_utc":"2026-12-30T08:30:00Z","energy_kwh":5.5731},
    {"start_utc":"2026-12-30T09:30:00Z","energy_kwh":5.2912},
    {"start_utc":"2026-12-30T10:30:00Z","energy_kwh":5.8248},
    {"start_utc":"2026-12-30T11:30:00Z","energy_kwh":5.0991},
    {"start_utc":"2026-12-30T12:30:00Z","energy_kwh":0.4375},
    {"start_utc":"2026-12-30T13:30:00Z","energy_kwh":0.4835},
    {"start_utc":"2026-12-30T14:30:00Z","energy_kwh":0.4902},
    {"start_utc":"2026-12-30T15:30:00Z","energy_kwh":0.4044},
    {"start_utc":"2026-12-30T16:30:00Z","energy_kwh":0.4624},
    {"start_utc":"2026-12-30T17:30:00Z","energy_kwh":0.3994},
    {"start_utc":"2026-12-30T18:30:00Z","energy_kwh":0.4298},
    {"start_utc":"2026-12-30T19:30:00Z","energy_kwh":0.4423},
    {"start_utc":"2026-12-30T20:30:00Z","energy_kwh":0.5386},
    {"start_utc":"2026-12-30T21:30:00Z","energy_kwh":0.3919},
    {"start_utc":"2026-12-30T22:30:00Z","energy_kwh":0.4203},
    {"start_utc":"2026-12-30T23:30:00Z","energy_kwh":0.4512},
    {"start_utc":"2026-12-31T00:30:00Z","energy_kwh":0.4637},
    {"start_utc":"2026-12-31T01:30:00Z","energy_kwh":0.4273},
    {"start_utc":"2026-12-31T02:30:00Z","energy_kwh":0.4451},
    {"start_utc":"2026-12-31T03:30:00Z","energy_kwh":5.314},
    {"start_utc":"2026-12-31T04:30:00Z","energy_kwh":4.7782},
    {"start_utc":"2026-12-31T05:30:00Z","energy_kwh":5.6263},
    {"start_utc":"2026-12-31T06:30:00Z","energy_kwh":5.6403},
    {"start_utc":"2026-12-31T07:30:00Z","energy_kwh":4.0399},
    {"start_utc":"2026-12-31T08:30:00Z","energy_kwh":5.4163},
    {"start_utc":"2026-12-31T09:30:00Z","energy_kwh":5.4195},
    {"start_utc":"2026-12-31T10:30:00Z","energy_kwh":5.0035},
    {"start_utc":"2026-12-31T11:30:00Z","energy_kwh":5.4623},
    {"start_utc":"2026-12-31T12:30:00Z","energy_kwh":0.4012},
    {"start_utc":"2026-12-31T13:30:00Z","energy_kwh":0.3922},
    {"start_utc":"2026-12-31T14:30:00Z","energy_kwh":0.4097},
    {"start_utc":"2026-12-31T15:30:00Z","energy_kwh":0.4647},
    {"start_utc":"2026-12-31T16:30:00Z","energy_kwh":0.4643},
    {"start_utc":"2026-12-31T17:30:00Z","energy_kwh":0.4693},
    {"start_utc":"2026-12-31T18:30:00Z","energy_kwh":0.4335},
    {"start_utc":"2026-12-31T19:30:00Z","energy_kwh":0.4153},
    {"start_utc":"2026-12-31T20:30:00Z","energy_kwh":0.4332},
    {"start_utc":"2026-12-31T21:30:00Z","energy_kwh":0.4572},
    {"start_utc":"2026-12-31T22:30:00Z","energy_kwh":0.419},
    {"start_utc":"2026-12-31T23:30:00Z","energy_kwh":0.4608},
    {"start_utc":"2027-01-01T00:30:00Z","energy_kwh":0.4233},
    {"start_utc":"2027-01-01T01:30:00Z","energy_kwh":0.4788},
    {"start_utc":"2027-01-01T02:30:00Z","energy_kwh":0.4394},
    {"start_utc":"2027-01-01T03:30:00Z","energy_kwh":5.6499},
    {"start_utc":"2027-01-01T04:30:00Z","energy_kwh":5.2192},
    {"start_utc":"2027-01-01T05:30:00Z","energy_kwh":5.1945},
    {"start_utc":"2027-01-01T06:30:00Z","energy_kwh":5.504},
    {"start_utc":"2027-01-01T07:30:00Z","energy_kwh":3.8943},
    {"start_utc":"2027-01-01T08:30:00Z","energy_kwh":5.667},
    {"start_utc":"2027-01-01T09:30:00Z","energy_kwh":5.421},
    {"start_utc":"2027-01-01T10:30:00Z","energy_kwh":5.2158},
    {"start_utc":"2027-01-01T11:30:00Z","energy_kwh":5.3414},
    {"start_utc":"2027-01-01T12:30:00Z","energy_kwh":0.3994},
    {"start_utc":"2027-01-01T13:30:00Z","energy_kwh":0.4404},
    {"start_utc":"2027-01-01T14:30:00Z","energy_kwh":0.5335},
    {"start_utc":"2027-01-01T15:30:00Z","energy_kwh":0.3934},
    {"start_utc":"2027-01-01T16:30:00Z","energy_kwh":0.4243},
    {"start_utc":"2027-01-01T17:30:00Z","energy_kwh":0.444},
    {"start_utc":"2027-01-01T18:30:00Z","energy_kwh":0.3833},
    {"start_utc":"2027-01-01T19:30:00Z","energy_kwh":0.4688},
    {"start_utc":"2027-01-01T20:30:00Z","energy_kwh":0.4056},
    {"start_utc":"2027-01-01T21:30:00Z","energy_kwh":0.4429},
    {"start_utc":"2027-01-01T22:30:00Z","energy_kwh":0.3737},
    {"start_utc":"2027-01-01T23:30:00Z","energy_kwh":0.4703},
    {"start_utc":"2027-01-02T00:30:00Z","energy_kwh":0.3881},
    {"start_utc":"2027-01-02T01:30:00Z","energy_kwh":0.5199},
    {"start_utc":"2027-01-02T02:30:00Z","energy_kwh":0.395},
    {"start_utc":"2027-01-02T03:30:00Z","energy_kwh":0.4709},
    {"start_utc":"2027-01-02T04:30:00Z","energy_kwh":0.4218},
    {"start_utc":"2027-01-02T05:30:00Z","energy_kwh":0.5163},
    {"start_utc":"2027-01-02T06:30:00Z","energy_kwh":0.361},
    {"start_utc":"2027-01-02T07:30:00Z","energy_kwh":0.4784},
    {"start_utc":"2027-01-02T08:30:00Z","energy_kwh":0.4051},
    {"start_utc":"2027-01-02T09:30:00Z","energy_kwh":0.5114},
    {"start_utc":"2027-01-02T10:30:00Z","energy_kwh":0.485},
    {"start_utc":"2027-01-02T11:30:00Z","energy_kwh":0.3931},
    {"start_utc":"2027-01-02T12:30:00Z","energy_kwh":0.4266},
    {"start_utc":"2027-01-02T13:30:00Z","energy_kwh":0.4621},
    {"start_utc":"2027-01-02T14:30:00Z","energy_kwh":0.501},
    {"start_utc":"2027-01-02T15:30:00Z","energy_kwh":0.4074},
    {"start_utc":"2027-01-02T16:30:00Z","energy_kwh":0.4707},
    {"start_utc":"2027-01-02T17:30:00Z","energy_kwh":0.4266},
    {"start_utc":"2027-01-02T18:30:00Z","energy_kwh":0.3925},
    {"start_utc":"2027-01-02T19:30:00Z","energy_kwh":0.467},
    {"start_utc":"2027-01-02T20:30:00Z","energy_kwh":0.5197},
    {"start_utc":"2027-01-02T21:30:00Z","energy_kwh":0.4478},
    {"start_utc":"2027-01-02T22:30:00Z","energy_kwh":0.4346},
    {"start_utc":"2027-01-02T23:30:00Z","energy_kwh":0.4164},
    {"start_utc":"2027-01-03T00:30:00Z","energy_kwh":0.5456},
    {"start_utc":"2027-01-03T01:30:00Z","energy_kwh":0.4369},
    {"start_utc":"2027-01-03T02:30:00Z","energy_kwh":0.4651},
    {"start_utc":"2027-01-03T03:30:00Z","energy_kwh":0.4623},
    {"start_utc":"2027-01-03T04:30:00Z","energy_kwh":0.455},
    {"start_utc":"2027-01-03T05:30:00Z","energy_kwh":0.4115},
    {"start_utc":"2027-01-03T06:30:00Z","energy_kwh":0.4366},
    {"start_utc":"2027-01-03T07:30:00Z","energy_kwh":0.4405},
    {"start_utc":"2027-01-03T08:30:00Z","energy_kwh":0.3548},
    {"start_utc":"2027-01-03T09:30:00Z","energy_kwh":0.428},
    {"start_utc":"2027-01-03T10:30:00Z","energy_kwh":0.4287},
    {"start_utc":"2027-01-03T11:30:00Z","energy_kwh":0.4231},
    {"start_utc":"2027-01-03T12:30:00Z","energy_kwh":0.4499},
    {"start_utc":"2027-01-03T13:30:00Z","energy_kwh":0.411},
    {"start_utc":"2027-01-03T14:30:00Z","energy_kwh":0.4555},
    {"start_utc":"2027-01-03T15:30:00Z","energy_kwh":0.4396},
    {"start_utc":"2027-01-03T16:30:00Z","energy_kwh":0.4478},
    {"start_utc":"2027-01-03T17:30:00Z","energy_kwh":0.4402}
  ],
  "calendar": {"timezone":"Asia/Kolkata","working_days_iso":[1,2,3,4,5],"open_local":"09:00","close_local":"18:00"},
  "future_assumptions": {"schedule":{"policy_id":"pol-light-a","version":1,"kind":"lighting_schedule","rules":{"on_during_hours":true,"vacancy_grace_seconds":300}},"environment":{"avg_temp_c":27.5,"avg_rh_pct":55}},
  "model": {"version":"hourly-profile-median-v1"}
}
```

### Complete response — HTTP 200

```json
{
  "data": {
    "horizon": "next_24h",
    "origin_utc": "2027-01-03T18:30:00Z",
    "model_version": null,
    "baseline_version": "hourly-profile-median-v1",
    "method": "statistical_baseline",
    "timezone": "Asia/Kolkata",
    "horizon_start_utc": "2027-01-03T18:30:00Z",
    "horizon_end_utc": "2027-01-04T18:30:00Z",
    "points": [
      {"start_utc":"2027-01-03T18:30:00Z","energy_kwh":0.4404,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-03T19:30:00Z","energy_kwh":0.4423,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-03T20:30:00Z","energy_kwh":0.4401,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-03T21:30:00Z","energy_kwh":0.4572,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-03T22:30:00Z","energy_kwh":0.4658,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-03T23:30:00Z","energy_kwh":0.4608,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T00:30:00Z","energy_kwh":0.4538,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T01:30:00Z","energy_kwh":0.4528,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T02:30:00Z","energy_kwh":0.4394,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T03:30:00Z","energy_kwh":5.5942,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T04:30:00Z","energy_kwh":5.2192,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T05:30:00Z","energy_kwh":5.6263,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T06:30:00Z","energy_kwh":5.6403,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T07:30:00Z","energy_kwh":4.0399,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T08:30:00Z","energy_kwh":5.667,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T09:30:00Z","energy_kwh":5.4195,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T10:30:00Z","energy_kwh":5.2158,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T11:30:00Z","energy_kwh":5.4623,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T12:30:00Z","energy_kwh":0.4284,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T13:30:00Z","energy_kwh":0.453,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T14:30:00Z","energy_kwh":0.4902,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T15:30:00Z","energy_kwh":0.4598,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T16:30:00Z","energy_kwh":0.4624,"basis":"day_class_hour","support":5},
      {"start_utc":"2027-01-04T17:30:00Z","energy_kwh":0.444,"basis":"day_class_hour","support":5}
    ],
    "total_energy_kwh": 54.6749,
    "uncertainty": "unavailable",
    "history_coverage": {"observed_hours":168,"span_start_utc":"2026-12-27T18:30:00Z","span_end_utc":"2027-01-03T18:30:00Z","span_hours":168,"missing_hours":0,"duplicates_deduped":0,"min_observed_hours_required":168},
    "basis_counts": {"weekday_hour":0,"day_class_hour":24,"hour_of_day":0},
    "assumptions": ["Hourly grid anchored at origin_utc; local weekday/hour in Asia/Kolkata.","Day class from calendar.working_days_iso [1, 2, 3, 4, 5], applied to history and horizon alike.","Each hour = median of observed history in the first supported level: same weekday+hour (>= 2 obs), same day-class+hour (>= 3), same hour (>= 3).","Missing history hours are excluded, never treated as zero."],
    "assumptions_recorded": {"schedule":{"policy_id":"pol-light-a","version":1,"kind":"lighting_schedule","rules":{"on_during_hours":true,"vacancy_grace_seconds":300}},"environment":{"avg_temp_c":27.5,"avg_rh_pct":55}},
    "limitations": ["Statistical profile baseline, not a trained model; no accuracy claim is made for this building.","No prediction interval or confidence is produced (uncertainty: unavailable).","Holidays, historical calendar changes, trends and one-off events are not modelled.","Weather, occupancy and schedule assumptions do not influence the result."],
    "warnings": [
      {"code":"FALLBACK_DAY_CLASS","message":"24 hour(s) used the working/non-working day-class profile because the same weekday/hour had too few observations."},
      {"code":"INPUTS_NOT_USED","message":"Accepted and recorded but not used by the baseline: calendar.open_local, calendar.close_local, future_assumptions.schedule, future_assumptions.environment. Only the observed hourly history and calendar.timezone/working_days_iso influence the forecast."}
    ]
  },
  "meta": {"request_id":"9cf7999a-4915-4b28-8c33-7e6faf454ae7"}
}
```

With exactly 7 days of history, each weekday appears once, so Monday hours
use the **working-day class** median (5 working days) and disclose
`FALLBACK_DAY_CLASS`. The total is 54.67 kWh for the 24 hours of Monday
2027-01-04 local.

## Auditor-backend integration instructions

1. **Build the history server-side** from the auditor's own database.
   - Build the history on the calendar's local-hour grid: sum each device's
     energy into complete local hours
     (`[HH:30Z, HH+1:30Z)` for Asia/Kolkata). Omit any hour lacking complete
     coverage; never send it as zero or as a partial value.
   - Send at most the latest **2,160** hours ending at or before the origin.
   - Pick a full local hour as the origin, e.g. the next local midnight.
   - Required for `next_calendar_month`: a local-clock origin.
2. **Send the calendar** from the dataset's office-hours policy in force:
   `timezone: "Asia/Kolkata"`, `working_days_iso`, `open_local`,
   `close_local`. Optionally record `future_assumptions`; the response
   reports them as not used.
3. **Call and handle the response:**
   - Call `POST {ML_SERVICE_URL}/v1/forecast` server-side.
   - On **422 `INSUFFICIENT_DATA`**, show the message ("needs N days of
     history").
   - On **413**, send fewer hours.
   - On 400, fix the request (the `field` says where).
4. **Mapping to the public API:** map the response to the auditor's
   `POST /api/v1/forecasts` (`forecast_id`, `horizon`, `origin_utc`,
   `model_version` = `null` with `baseline_version`, `points`,
   `uncertainty: "unavailable"`).
   - Compute cost in the auditor as `total_energy_kwh × tariff`: an unset
     tariff means unset cost; a zero tariff means zero cost.
   - Changing the tariff never re-requests the forecast.
5. **Labelling:** label the results as a **statistical baseline** in the UI,
   not ML, with no confidence band.

## Limitations

- It is a profile baseline:
  - no trend, seasonality beyond the weekly profile, holidays, special
    events, or historical calendar changes (one calendar classifies all
    days);
  - no weather, occupancy or schedule sensitivity;
  - no uncertainty.
- Only Asia/Kolkata is accepted. A month forecast requires a local-clock
  origin.
- Accuracy has only been measured on synthetic data; it has **not** been
  validated on real or simulated building exports.
- Up to 2,160 hours of context (90 days) is available per request.

## Next model-development steps (future assignments)

1. Evaluate on simulator exports once history generation and export exist.
   Compare with a real holdout from a different period than any tuning.
2. Candidate improvements, each measured against this baseline with
   chronological holdouts: holiday/calendar features, a recency-weighted
   profile, weather/occupancy regressors when real inputs exist, and
   empirical prediction intervals from holdout residuals.
3. Only a validated, versioned trained model may set `model_available: true`
   and a non-null `model_version`.
