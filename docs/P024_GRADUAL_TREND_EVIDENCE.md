# P024_GRADUAL_TREND_EVIDENCE — gradual consumption trend detection (M5)

Agent B — Claude Code | P024 | M5. Owner Mohan. Date 2026-09-25. Scope:
`energy-ml-service` only. Implementation is **completed**; review is
**pending**. The commit hash is reported in the P024 return report after the
push.

- **Starting state:** `b17e54b` (P022, accepted for its narrow scope) equal
  to `origin/main`, with a clean tree.
- **Analysis scenarios now implemented:** vacancy operation
  (`/v1/analyze`), excess-consumption deviation (`/v1/anomalies`), and
  gradual upward consumption (`/v1/drift`, this task).
- **What this is not:** an upward power trend is **not** confirmed
  efficiency deterioration. Delivered output, outdoor conditions, setpoints
  and workload are not observed, so efficiency cannot be established from
  power alone.

## 1. P022 environmental-claim correction

- **What was wrong:** P022 documentation (and a detector docstring) said a
  temperature or occupancy change alone "never" produces a finding. That
  overstated it.
- **Corrected wording:** "Matching observed context reduces confounding but
  does not eliminate unmeasured differences such as outdoor temperature,
  setpoint or workload."
- **Where it was corrected:**
  - `docs/P022_EXCESS_CONSUMPTION_EVIDENCE.md`: a dated correction note plus
    the comparability rule text;
  - the synthetic-results caveat;
  - the `app/anomalies/detector.py` docstring.
- **Behaviour unchanged:** P022 detector behaviour is unchanged, and all 24
  `/v1/anomalies` tests pass. The only code change to P022 is that
  `parse_anomaly_request` takes the expected detector version as a
  parameter, defaulting to P022's own, so `/v1/drift` can reuse it.

## 2. Endpoint (additive local extension; shared contract unchanged)

`POST /v1/drift`, called server-side by auditor-backend. It uses the existing
success/error envelopes.

- **Request format** `drift-request-v1`: the same structure and validation as
  P022's `/v1/anomalies`:
  - `contract_version`, `dataset_id`, `run_id`, `rooms`, `devices`,
    `policies`;
  - an earlier `reference{window, room_intervals, device_intervals}`;
  - a later `evaluation{…}`;
  - optional `detector{version: "gradual-power-trend-v1"}`.
- **Limits:**
  - **≤ 2,000 device and ≤ 2,000 room intervals per section** (413
    `REQUEST_TOO_LARGE` naming the section; **never aggregated inside
    Python**);
  - body ≤ 16 MiB (413).
- **Separation:** `reference.window.end_utc` must be ≤
  `evaluation.window.start_utc` (else 400).
- **Rejected with 400 (P010 semantic checks per section):** invalid
  timestamps, unresolved references, conflicting duplicates, non-finite
  values and fault labels. Identical duplicates are deduplicated and don't
  add support.
- **Bounds in practice:** several days of support need **coarse or selective
  intervals**. For example, hourly intervals over working hours for a few
  devices: 4 devices × 9 h × 28 days = 1,008 records. Minute data for many
  devices won't fit; the caller must send coarser contract intervals (the
  contract supports 3,600 s) or fewer devices per request. Otherwise the
  response is `insufficient_history`; requirements are not weakened.

## 3. Comparability and temporal support (frozen before evaluation)

**Comparable observations** (per device; never across devices):
- **Duty:** fully on (`on_fraction == 1`) and not partial. Off, mixed-duty,
  duty-unknown and partial intervals are excluded, and power is **never
  divided by `on_fraction`**.
- **Group power:** the reported `avg_power_w` is the whole device/group and
  is **never multiplied by `quantity`**.
- **One resolution:** the most common reference `interval_seconds`; others
  are excluded (`resolution_mismatch`).
- **One configuration:** the reference's dominant `policy_ref`. Evaluation
  observations under another policy version are excluded (`policy_changed`),
  so a configuration change is never attributed to the equipment. When
  everything is excluded this way, the device status is
  `unsupported_context`.
- **Context normalisation:** ratio = power ÷ the reference median of the same
  **context**. A context baseline needs ≥ **3 distinct reference days**;
  otherwise the observation is excluded (`no_reference_for_context`).
  - **Ordinary devices:** context = local hour (Asia/Kolkata), so a change in
    *which hours are sampled* is not a trend.
  - **Comfort-dependent devices** (ac, refrigerator): context = (1 °C room
    temperature bin, occupied yes/no). This **reduces but does not remove**
    confounding: outdoor temperature, setpoint and workload are unobserved.
    Evaluation conditions without matching reference conditions are
    excluded, not guessed.

**Daily summaries and support:**
- **Supported day** (local calendar date): ≥ **3** comparable observations
  and ≥ **1 h** of fully-on comparable time. The day's value is the median
  ratio. Many readings in one day count as **one** day.
- **Reference:** ≥ **5** supported days spanning ≥ **7** days.
- **Evaluation:** ≥ **10** supported days spanning ≥ **14** days, with ≥
  **50 %** of calendar days in the span supported.
- **Gaps:** missing days are **not bridged**, and elapsed time uses actual
  calendar days (not row numbers).

## 4. Trend method, thresholds and classification (frozen before evaluation)

**Baseline:** per-context reference medians; the reference level (W) is the
median comparable reference power.

**Trend estimator:** Theil–Sen, the median pairwise slope of daily ratios
against actual elapsed days. Change over the period = slope × (span − 1).
Classification, in order:

| Classification | Rule | Returned as |
|---|---|---|
| `abrupt_level_change` | L1 changepoint split (≥ 3 days per side; minimum total absolute deviation from segment medians) with level change ≥ **10 %** while each segment's own Theil–Sen change ≤ **3 %** | `other_changes` (never a trend finding) |
| `sustained_upward_trend` | change ≥ **10 %** of the reference level **and** ≥ **10 W**, **and** persistence: chronological thirds' medians strictly increasing and ≥ **75 %** of final-third days at ratio ≥ **1.05** | **finding** |
| `upward_change_not_sustained` | change ≥ 10 % but persistence fails | `other_changes` |
| `level_offset_without_trend` | median ratio ≥ **1.10** without a qualifying trend (elevated from the start) | `other_changes` |
| `stable` | otherwise | device entry |

- **Spikes:** isolated spike days (ratio ≥ 1.25, no adjacent spike day) are
  listed in `spike_days`. The robust estimator and the persistence rule stop
  a spike from becoming a trend.
- **Gradual vs abrupt:**
  - a **step** is a level change with flat segments on both sides, so it is
    described as an abrupt level change;
  - a **gradual** increase keeps rising *within* segments, so it fails the
    ≤ 3 % within-segment rule and must also pass persistence;
  - an elevated level present from the start is an **offset**, not a trend.
- **Development fix (before the held-out run; thresholds unchanged):** the
  first "best split" rule (largest median jump) was not unique, and a
  development step case was misread as a trend. The split is now the L1
  changepoint. This is logged in PROGRESS_LOG.
- **No significance claims:** there are no confidence percentages or p-values.

**Findings** (`finding_type: "sustained_upward_power_trend"`, title
"Sustained upward power trend under matched observed conditions"):
- **What and when:** device, room and assessed period (first and last local
  date, span, timezone), and the reference level in W.
- **Trend:** `watts_per_day`, `relative_per_day`,
  `relative_change_over_period` and `watts_change_over_period`.
- **Support and persistence:** persistence evidence; supported
  days/observations and exclusions; daily evidence.
- **Labels and text:** `method: "rule"`,
  `technique: "theil_sen_context_normalised_daily"`, `detector_version`,
  assumptions, limitations, and a suggested *investigation*.
- **Not included:** no avoidable kWh, savings, ROI or failure cause, and a
  `NOT_ADDITIVE` warning says not to sum trends with vacancy or
  excess-consumption results.

**Statuses:** the overall `status` is `findings_detected`,
`evaluated_no_gradual_trend`, `insufficient_history`, `unsupported_context`
or `no_comparable_observations`. Every device has a `status`, a
`classification` and a `reason`. `coverage` counts devices by status and
intervals by section, and `exclusions[]` lists individual excluded intervals
with reasons. "No findings" therefore never implies every device was
evaluated. `model_available` stays `false`.

## 5. Live HTTP evidence (127.0.0.1:8000, SYNTHETIC requests)

- **Start command:** `.venv\Scripts\python.exe -m app`, with launcher PID
  8684 and interpreter PID 9644. Both were stopped afterwards and port 8000
  was free. **No process is left running.**
- **Regression checks** on the same server:
  - `/v1/anomalies` (P022 example) → 200, `findings_detected`, 104.8 W vs a
    threshold of 82 W;
  - `/v1/analyze` (P010 fixture) → 200, 1 finding, 0.01 kWh avoidable;
  - `/v1/forecast` (P013 example) → 200, 24 points, 54.6749 kWh;
  - `/health` → `model_available: false`.

### Trend case — request (one light, local 10:00–13:00; reference 7 days, evaluation 14 days rising ~30 %)

```json
{
  "contract_version": "1.0.1",
  "dataset_id": "ds-synthetic-drift",
  "run_id": "run-synthetic-drift",
  "rooms": [
    {"room_id":"room-a","name":"Room A","capacity":12},
    {"room_id":"room-b","name":"Room B","capacity":4}
  ],
  "devices": [
    {
      "device_id": "light-a",
      "name": "Room A light",
      "room_id": "room-a",
      "device_type": "lighting",
      "always_on": false,
      "quantity": 1,
      "nominal_power_w": 72,
      "standby_power_w": 0,
      "control": "scheduled"
    }
  ],
  "policies": [
    {"policy_id":"pol-light-a","version":1,"kind":"lighting_schedule","rules":{"on_during_hours":true,"vacancy_grace_seconds":300}}
  ],
  "reference": {
    "window": {
      "start_utc": "2026-01-04T18:30:00Z",
      "end_utc": "2026-01-11T18:30:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-01-05T04:30:00Z","interval_end_utc":"2026-01-05T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-05T05:30:00Z","interval_end_utc":"2026-01-05T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-05T06:30:00Z","interval_end_utc":"2026-01-05T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-06T04:30:00Z","interval_end_utc":"2026-01-06T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-06T05:30:00Z","interval_end_utc":"2026-01-06T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-06T06:30:00Z","interval_end_utc":"2026-01-06T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-07T04:30:00Z","interval_end_utc":"2026-01-07T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-07T05:30:00Z","interval_end_utc":"2026-01-07T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-07T06:30:00Z","interval_end_utc":"2026-01-07T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-08T04:30:00Z","interval_end_utc":"2026-01-08T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-08T05:30:00Z","interval_end_utc":"2026-01-08T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-08T06:30:00Z","interval_end_utc":"2026-01-08T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-09T04:30:00Z","interval_end_utc":"2026-01-09T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-09T05:30:00Z","interval_end_utc":"2026-01-09T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-09T06:30:00Z","interval_end_utc":"2026-01-09T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-10T04:30:00Z","interval_end_utc":"2026-01-10T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-10T05:30:00Z","interval_end_utc":"2026-01-10T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-10T06:30:00Z","interval_end_utc":"2026-01-10T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-11T04:30:00Z","interval_end_utc":"2026-01-11T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-11T05:30:00Z","interval_end_utc":"2026-01-11T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-11T06:30:00Z","interval_end_utc":"2026-01-11T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-05T04:30:00Z","interval_end_utc":"2026-01-05T05:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-05T05:30:00Z","interval_end_utc":"2026-01-05T06:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-05T06:30:00Z","interval_end_utc":"2026-01-05T07:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-06T04:30:00Z","interval_end_utc":"2026-01-06T05:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-06T05:30:00Z","interval_end_utc":"2026-01-06T06:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-06T06:30:00Z","interval_end_utc":"2026-01-06T07:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-07T04:30:00Z","interval_end_utc":"2026-01-07T05:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-07T05:30:00Z","interval_end_utc":"2026-01-07T06:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-07T06:30:00Z","interval_end_utc":"2026-01-07T07:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-08T04:30:00Z","interval_end_utc":"2026-01-08T05:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-08T05:30:00Z","interval_end_utc":"2026-01-08T06:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-08T06:30:00Z","interval_end_utc":"2026-01-08T07:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-09T04:30:00Z","interval_end_utc":"2026-01-09T05:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-09T05:30:00Z","interval_end_utc":"2026-01-09T06:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-09T06:30:00Z","interval_end_utc":"2026-01-09T07:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-10T04:30:00Z","interval_end_utc":"2026-01-10T05:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-10T05:30:00Z","interval_end_utc":"2026-01-10T06:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-10T06:30:00Z","interval_end_utc":"2026-01-10T07:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-11T04:30:00Z","interval_end_utc":"2026-01-11T05:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-11T05:30:00Z","interval_end_utc":"2026-01-11T06:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-11T06:30:00Z","interval_end_utc":"2026-01-11T07:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  },
  "evaluation": {
    "window": {
      "start_utc": "2026-01-11T18:30:00Z",
      "end_utc": "2026-01-25T18:30:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-01-12T04:30:00Z","interval_end_utc":"2026-01-12T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-12T05:30:00Z","interval_end_utc":"2026-01-12T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-12T06:30:00Z","interval_end_utc":"2026-01-12T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-13T04:30:00Z","interval_end_utc":"2026-01-13T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-13T05:30:00Z","interval_end_utc":"2026-01-13T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-13T06:30:00Z","interval_end_utc":"2026-01-13T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-14T04:30:00Z","interval_end_utc":"2026-01-14T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-14T05:30:00Z","interval_end_utc":"2026-01-14T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-14T06:30:00Z","interval_end_utc":"2026-01-14T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-15T04:30:00Z","interval_end_utc":"2026-01-15T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-15T05:30:00Z","interval_end_utc":"2026-01-15T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-15T06:30:00Z","interval_end_utc":"2026-01-15T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-16T04:30:00Z","interval_end_utc":"2026-01-16T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-16T05:30:00Z","interval_end_utc":"2026-01-16T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-16T06:30:00Z","interval_end_utc":"2026-01-16T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-17T04:30:00Z","interval_end_utc":"2026-01-17T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-17T05:30:00Z","interval_end_utc":"2026-01-17T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-17T06:30:00Z","interval_end_utc":"2026-01-17T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-18T04:30:00Z","interval_end_utc":"2026-01-18T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-18T05:30:00Z","interval_end_utc":"2026-01-18T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-18T06:30:00Z","interval_end_utc":"2026-01-18T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-19T04:30:00Z","interval_end_utc":"2026-01-19T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-19T05:30:00Z","interval_end_utc":"2026-01-19T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-19T06:30:00Z","interval_end_utc":"2026-01-19T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-20T04:30:00Z","interval_end_utc":"2026-01-20T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-20T05:30:00Z","interval_end_utc":"2026-01-20T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-20T06:30:00Z","interval_end_utc":"2026-01-20T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-21T04:30:00Z","interval_end_utc":"2026-01-21T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-21T05:30:00Z","interval_end_utc":"2026-01-21T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-21T06:30:00Z","interval_end_utc":"2026-01-21T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-22T04:30:00Z","interval_end_utc":"2026-01-22T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-22T05:30:00Z","interval_end_utc":"2026-01-22T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-22T06:30:00Z","interval_end_utc":"2026-01-22T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-23T04:30:00Z","interval_end_utc":"2026-01-23T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-23T05:30:00Z","interval_end_utc":"2026-01-23T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-23T06:30:00Z","interval_end_utc":"2026-01-23T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-24T04:30:00Z","interval_end_utc":"2026-01-24T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-24T05:30:00Z","interval_end_utc":"2026-01-24T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-24T06:30:00Z","interval_end_utc":"2026-01-24T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-25T04:30:00Z","interval_end_utc":"2026-01-25T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-25T05:30:00Z","interval_end_utc":"2026-01-25T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-25T06:30:00Z","interval_end_utc":"2026-01-25T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-12T04:30:00Z","interval_end_utc":"2026-01-12T05:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-12T05:30:00Z","interval_end_utc":"2026-01-12T06:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-12T06:30:00Z","interval_end_utc":"2026-01-12T07:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-13T04:30:00Z","interval_end_utc":"2026-01-13T05:30:00Z","interval_seconds":3600,"avg_power_w":74.398,"max_power_w":74.398,"energy_kwh":0.07439799999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-13T05:30:00Z","interval_end_utc":"2026-01-13T06:30:00Z","interval_seconds":3600,"avg_power_w":75.135,"max_power_w":75.135,"energy_kwh":0.075135,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-13T06:30:00Z","interval_end_utc":"2026-01-13T07:30:00Z","interval_seconds":3600,"avg_power_w":72.188,"max_power_w":72.188,"energy_kwh":0.072188,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-14T04:30:00Z","interval_end_utc":"2026-01-14T05:30:00Z","interval_seconds":3600,"avg_power_w":74.57,"max_power_w":74.57,"energy_kwh":0.07457,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-14T05:30:00Z","interval_end_utc":"2026-01-14T06:30:00Z","interval_seconds":3600,"avg_power_w":75.323,"max_power_w":75.323,"energy_kwh":0.075323,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-14T06:30:00Z","interval_end_utc":"2026-01-14T07:30:00Z","interval_seconds":3600,"avg_power_w":76.076,"max_power_w":76.076,"energy_kwh":0.07607599999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-15T04:30:00Z","interval_end_utc":"2026-01-15T05:30:00Z","interval_seconds":3600,"avg_power_w":78.524,"max_power_w":78.524,"energy_kwh":0.07852400000000001,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-15T05:30:00Z","interval_end_utc":"2026-01-15T06:30:00Z","interval_seconds":3600,"avg_power_w":75.445,"max_power_w":75.445,"energy_kwh":0.075445,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-15T06:30:00Z","interval_end_utc":"2026-01-15T07:30:00Z","interval_seconds":3600,"avg_power_w":76.215,"max_power_w":76.215,"energy_kwh":0.076215,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-16T04:30:00Z","interval_end_utc":"2026-01-16T05:30:00Z","interval_seconds":3600,"avg_power_w":78.646,"max_power_w":78.646,"energy_kwh":0.078646,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-16T05:30:00Z","interval_end_utc":"2026-01-16T06:30:00Z","interval_seconds":3600,"avg_power_w":79.433,"max_power_w":79.433,"energy_kwh":0.07943300000000002,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-16T06:30:00Z","interval_end_utc":"2026-01-16T07:30:00Z","interval_seconds":3600,"avg_power_w":80.219,"max_power_w":80.219,"energy_kwh":0.08021899999999998,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-17T04:30:00Z","interval_end_utc":"2026-01-17T05:30:00Z","interval_seconds":3600,"avg_power_w":78.702,"max_power_w":78.702,"energy_kwh":0.07870200000000001,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-17T05:30:00Z","interval_end_utc":"2026-01-17T06:30:00Z","interval_seconds":3600,"avg_power_w":79.505,"max_power_w":79.505,"energy_kwh":0.079505,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-17T06:30:00Z","interval_end_utc":"2026-01-17T07:30:00Z","interval_seconds":3600,"avg_power_w":80.308,"max_power_w":80.308,"energy_kwh":0.08030800000000002,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-18T04:30:00Z","interval_end_utc":"2026-01-18T05:30:00Z","interval_seconds":3600,"avg_power_w":82.789,"max_power_w":82.789,"energy_kwh":0.082789,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-18T05:30:00Z","interval_end_utc":"2026-01-18T06:30:00Z","interval_seconds":3600,"avg_power_w":83.609,"max_power_w":83.609,"energy_kwh":0.08360899999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-18T06:30:00Z","interval_end_utc":"2026-01-18T07:30:00Z","interval_seconds":3600,"avg_power_w":80.33,"max_power_w":80.33,"energy_kwh":0.08033,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-19T04:30:00Z","interval_end_utc":"2026-01-19T05:30:00Z","interval_seconds":3600,"avg_power_w":82.794,"max_power_w":82.794,"energy_kwh":0.08279399999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-19T05:30:00Z","interval_end_utc":"2026-01-19T06:30:00Z","interval_seconds":3600,"avg_power_w":83.631,"max_power_w":83.631,"energy_kwh":0.083631,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-19T06:30:00Z","interval_end_utc":"2026-01-19T07:30:00Z","interval_seconds":3600,"avg_power_w":84.467,"max_power_w":84.467,"energy_kwh":0.084467,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-20T04:30:00Z","interval_end_utc":"2026-01-20T05:30:00Z","interval_seconds":3600,"avg_power_w":86.998,"max_power_w":86.998,"energy_kwh":0.08699799999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-20T05:30:00Z","interval_end_utc":"2026-01-20T06:30:00Z","interval_seconds":3600,"avg_power_w":83.586,"max_power_w":83.586,"energy_kwh":0.083586,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-20T06:30:00Z","interval_end_utc":"2026-01-20T07:30:00Z","interval_seconds":3600,"avg_power_w":84.439,"max_power_w":84.439,"energy_kwh":0.08443899999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-21T04:30:00Z","interval_end_utc":"2026-01-21T05:30:00Z","interval_seconds":3600,"avg_power_w":86.954,"max_power_w":86.954,"energy_kwh":0.08695399999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-21T05:30:00Z","interval_end_utc":"2026-01-21T06:30:00Z","interval_seconds":3600,"avg_power_w":87.823,"max_power_w":87.823,"energy_kwh":0.087823,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-21T06:30:00Z","interval_end_utc":"2026-01-21T07:30:00Z","interval_seconds":3600,"avg_power_w":88.693,"max_power_w":88.693,"energy_kwh":0.088693,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-22T04:30:00Z","interval_end_utc":"2026-01-22T05:30:00Z","interval_seconds":3600,"avg_power_w":86.843,"max_power_w":86.843,"energy_kwh":0.086843,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-22T05:30:00Z","interval_end_utc":"2026-01-22T06:30:00Z","interval_seconds":3600,"avg_power_w":87.729,"max_power_w":87.729,"energy_kwh":0.087729,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-22T06:30:00Z","interval_end_utc":"2026-01-22T07:30:00Z","interval_seconds":3600,"avg_power_w":88.615,"max_power_w":88.615,"energy_kwh":0.088615,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-23T04:30:00Z","interval_end_utc":"2026-01-23T05:30:00Z","interval_seconds":3600,"avg_power_w":91.18,"max_power_w":91.18,"energy_kwh":0.09118,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-23T05:30:00Z","interval_end_utc":"2026-01-23T06:30:00Z","interval_seconds":3600,"avg_power_w":92.082,"max_power_w":92.082,"energy_kwh":0.09208199999999998,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-23T06:30:00Z","interval_end_utc":"2026-01-23T07:30:00Z","interval_seconds":3600,"avg_power_w":88.471,"max_power_w":88.471,"energy_kwh":0.08847100000000001,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-24T04:30:00Z","interval_end_utc":"2026-01-24T05:30:00Z","interval_seconds":3600,"avg_power_w":91.019,"max_power_w":91.019,"energy_kwh":0.091019,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-24T05:30:00Z","interval_end_utc":"2026-01-24T06:30:00Z","interval_seconds":3600,"avg_power_w":91.938,"max_power_w":91.938,"energy_kwh":0.09193799999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-24T06:30:00Z","interval_end_utc":"2026-01-24T07:30:00Z","interval_seconds":3600,"avg_power_w":92.858,"max_power_w":92.858,"energy_kwh":0.092858,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-25T04:30:00Z","interval_end_utc":"2026-01-25T05:30:00Z","interval_seconds":3600,"avg_power_w":95.472,"max_power_w":95.472,"energy_kwh":0.09547199999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-25T05:30:00Z","interval_end_utc":"2026-01-25T06:30:00Z","interval_seconds":3600,"avg_power_w":91.728,"max_power_w":91.728,"energy_kwh":0.09172799999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-25T06:30:00Z","interval_end_utc":"2026-01-25T07:30:00Z","interval_seconds":3600,"avg_power_w":92.664,"max_power_w":92.664,"energy_kwh":0.09266400000000001,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  },
  "detector": {
    "version": "gradual-power-trend-v1"
  }
}
```

### Trend case — response (HTTP 200)

```json
{
  "data": {
    "status": "findings_detected",
    "findings": [
      {
        "finding_id": "sustained_upward_power_trend:light-a:2026-01-12",
        "finding_type": "sustained_upward_power_trend",
        "title": "Sustained upward power trend under matched observed conditions",
        "device_id": "light-a",
        "room_id": "room-a",
        "assessed_period": {
          "first_local_date": "2026-01-12",
          "last_local_date": "2026-01-25",
          "span_days": 14,
          "timezone": "Asia/Kolkata"
        },
        "reference_level_w": 72,
        "trend": {
          "watts_per_day": 1.6450000000000014,
          "relative_per_day": 0.02284722222222224,
          "relative_change_over_period": 0.29701388888888913,
          "watts_change_over_period": 21.38500000000002
        },
        "persistence": {
          "thirds_median_ratio": [
            1.0397291666666666,
            1.1498472222222222,
            1.266388888888889
          ],
          "final_third_elevated_share": 1
        },
        "support": {
          "reference_days": 7,
          "evaluation_days": 14,
          "evaluation_observations": 42,
          "reference_observations": 21,
          "evaluation_excluded": {},
          "reference_excluded": {}
        },
        "method": "rule",
        "technique": "theil_sen_context_normalised_daily",
        "detector_version": "gradual-power-trend-v1",
        "suggested_action": "Investigate the Room A light in Room A: compare settings, connected load, maintenance state and operating conditions over this period before attributing a cause.",
        "assumptions": "Compared only with this device's own fully-on observations at the same resolution and configuration (pol-light-a:1); power is the reported whole-device/group value (quantity not applied). Each observation is normalised by the reference median of its context (local hour), so a change in which hours are sampled is not counted as a trend. Trend = Theil–Sen median pairwise slope of supported daily median ratios against actual elapsed days; missing days are not filled. A rising power trend does not establish reduced efficiency, a fault or its cause: delivered output, outdoor conditions, setpoints and workload are not observed.",
        "limitations": "Not an efficiency or fault diagnosis; no avoidable-energy, savings or ROI estimate; must not be added to vacancy or excess-consumption findings.",
        "evidence": {
          "daily": [
            {"local_date":"2026-01-12","elapsed_days":0,"ratio_to_reference":0.99,"observations":3},
            {"local_date":"2026-01-13","elapsed_days":1,"ratio_to_reference":1.0333055555555555,"observations":3},
            {"local_date":"2026-01-14","elapsed_days":2,"ratio_to_reference":1.0461527777777777,"observations":3},
            {"local_date":"2026-01-15","elapsed_days":3,"ratio_to_reference":1.0585416666666667,"observations":3},
            {"local_date":"2026-01-16","elapsed_days":4,"ratio_to_reference":1.1032361111111113,"observations":3},
            {"local_date":"2026-01-17","elapsed_days":5,"ratio_to_reference":1.104236111111111,"observations":3},
            {"local_date":"2026-01-18","elapsed_days":6,"ratio_to_reference":1.1498472222222222,"observations":3},
            {"local_date":"2026-01-19","elapsed_days":7,"ratio_to_reference":1.1615416666666667,"observations":3},
            {"local_date":"2026-01-20","elapsed_days":8,"ratio_to_reference":1.1727638888888887,"observations":3},
            {"local_date":"2026-01-21","elapsed_days":9,"ratio_to_reference":1.2197638888888889,"observations":3},
            {"local_date":"2026-01-22","elapsed_days":10,"ratio_to_reference":1.2184583333333334,"observations":3},
            {"local_date":"2026-01-23","elapsed_days":11,"ratio_to_reference":1.266388888888889,"observations":3},
            {"local_date":"2026-01-24","elapsed_days":12,"ratio_to_reference":1.2769166666666667,"observations":3},
            {"local_date":"2026-01-25","elapsed_days":13,"ratio_to_reference":1.287,"observations":3}
          ],
          "spike_days": []
        }
      }
    ],
    "other_changes": [],
    "devices": [
      {
        "device_id": "light-a",
        "room_id": "room-a",
        "device_type": "lighting",
        "status": "evaluated",
        "classification": "sustained_upward_trend",
        "reason": null,
        "context": "local hour",
        "resolution_seconds": 3600,
        "policy_ref": "pol-light-a:1",
        "reference_level_w": 72,
        "contexts_with_baseline": 3,
        "support": {
          "reference_days": 7,
          "evaluation_days": 14,
          "evaluation_span_days": 14,
          "reference_observations": 21,
          "evaluation_observations": 42
        },
        "excluded": {
          "reference": {},
          "evaluation": {}
        },
        "spike_days": []
      }
    ],
    "coverage": {
      "devices": 1,
      "evaluated": 1,
      "insufficient_history": 0,
      "unsupported_context": 0,
      "no_comparable_observations": 0,
      "reference_device_intervals": 21,
      "evaluation_device_intervals": 42
    },
    "exclusions": [],
    "warnings": [
      {
        "code": "NOT_AN_EFFICIENCY_DIAGNOSIS",
        "message": "A sustained upward power trend under matched observed conditions does not establish reduced efficiency or a fault: delivered output, outdoor conditions, setpoints and workload are not observed."
      },
      {
        "code": "NOT_ADDITIVE",
        "message": "Do not add trend magnitudes to vacancy or excess-consumption findings; they can overlap."
      }
    ],
    "detector": {
      "version": "gradual-power-trend-v1",
      "method": "rule",
      "technique": "theil_sen_context_normalised_daily",
      "request_format": "drift-request-v1",
      "model_used": false,
      "parameters": {
        "building_timezone": "Asia/Kolkata",
        "comfort_temp_bin_c": 1,
        "final_third_elevated_ratio": 1.05,
        "final_third_elevated_share": 0.75,
        "max_exclusions_listed": 200,
        "min_absolute_change_w": 10,
        "min_context_reference_days": 3,
        "min_day_observations": 3,
        "min_day_on_seconds": 3600,
        "min_evaluation_days": 10,
        "min_evaluation_day_coverage": 0.5,
        "min_evaluation_span_days": 14,
        "min_reference_days": 5,
        "min_reference_span_days": 7,
        "min_relative_change": 0.1,
        "offset_min_ratio": 1.1,
        "spike_ratio": 1.25,
        "step_max_within_segment": 0.03,
        "step_min_change": 0.1,
        "step_min_segment_days": 3
      }
    },
    "analysis": {
      "contract_version": "1.0.1",
      "dataset_id": "ds-synthetic-drift",
      "run_id": "run-synthetic-drift",
      "reference_window": {
        "start_utc": "2026-01-04T18:30:00Z",
        "end_utc": "2026-01-11T18:30:00Z"
      },
      "evaluation_window": {
        "start_utc": "2026-01-11T18:30:00Z",
        "end_utc": "2026-01-25T18:30:00Z"
      },
      "bounds": {
        "device_intervals_per_section": 2000,
        "room_intervals_per_section": 2000
      }
    }
  },
  "meta": {
    "request_id": "38e90078-104f-475b-ae8d-0b9c6e901703"
  }
}
```

### Insufficient-history case — request (evaluation only 6 days)

```json
{
  "contract_version": "1.0.1",
  "dataset_id": "ds-synthetic-drift",
  "run_id": "run-synthetic-drift",
  "rooms": [
    {"room_id":"room-a","name":"Room A","capacity":12},
    {"room_id":"room-b","name":"Room B","capacity":4}
  ],
  "devices": [
    {
      "device_id": "light-a",
      "name": "Room A light",
      "room_id": "room-a",
      "device_type": "lighting",
      "always_on": false,
      "quantity": 1,
      "nominal_power_w": 72,
      "standby_power_w": 0,
      "control": "scheduled"
    }
  ],
  "policies": [
    {"policy_id":"pol-light-a","version":1,"kind":"lighting_schedule","rules":{"on_during_hours":true,"vacancy_grace_seconds":300}}
  ],
  "reference": {
    "window": {
      "start_utc": "2026-01-04T18:30:00Z",
      "end_utc": "2026-01-11T18:30:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-01-05T04:30:00Z","interval_end_utc":"2026-01-05T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-05T05:30:00Z","interval_end_utc":"2026-01-05T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-05T06:30:00Z","interval_end_utc":"2026-01-05T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-06T04:30:00Z","interval_end_utc":"2026-01-06T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-06T05:30:00Z","interval_end_utc":"2026-01-06T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-06T06:30:00Z","interval_end_utc":"2026-01-06T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-07T04:30:00Z","interval_end_utc":"2026-01-07T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-07T05:30:00Z","interval_end_utc":"2026-01-07T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-07T06:30:00Z","interval_end_utc":"2026-01-07T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-08T04:30:00Z","interval_end_utc":"2026-01-08T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-08T05:30:00Z","interval_end_utc":"2026-01-08T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-08T06:30:00Z","interval_end_utc":"2026-01-08T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-09T04:30:00Z","interval_end_utc":"2026-01-09T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-09T05:30:00Z","interval_end_utc":"2026-01-09T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-09T06:30:00Z","interval_end_utc":"2026-01-09T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-10T04:30:00Z","interval_end_utc":"2026-01-10T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-10T05:30:00Z","interval_end_utc":"2026-01-10T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-10T06:30:00Z","interval_end_utc":"2026-01-10T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-11T04:30:00Z","interval_end_utc":"2026-01-11T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-11T05:30:00Z","interval_end_utc":"2026-01-11T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-11T06:30:00Z","interval_end_utc":"2026-01-11T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-05T04:30:00Z","interval_end_utc":"2026-01-05T05:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-05T05:30:00Z","interval_end_utc":"2026-01-05T06:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-05T06:30:00Z","interval_end_utc":"2026-01-05T07:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-06T04:30:00Z","interval_end_utc":"2026-01-06T05:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-06T05:30:00Z","interval_end_utc":"2026-01-06T06:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-06T06:30:00Z","interval_end_utc":"2026-01-06T07:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-07T04:30:00Z","interval_end_utc":"2026-01-07T05:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-07T05:30:00Z","interval_end_utc":"2026-01-07T06:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-07T06:30:00Z","interval_end_utc":"2026-01-07T07:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-08T04:30:00Z","interval_end_utc":"2026-01-08T05:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-08T05:30:00Z","interval_end_utc":"2026-01-08T06:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-08T06:30:00Z","interval_end_utc":"2026-01-08T07:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-09T04:30:00Z","interval_end_utc":"2026-01-09T05:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-09T05:30:00Z","interval_end_utc":"2026-01-09T06:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-09T06:30:00Z","interval_end_utc":"2026-01-09T07:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-10T04:30:00Z","interval_end_utc":"2026-01-10T05:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-10T05:30:00Z","interval_end_utc":"2026-01-10T06:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-10T06:30:00Z","interval_end_utc":"2026-01-10T07:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-11T04:30:00Z","interval_end_utc":"2026-01-11T05:30:00Z","interval_seconds":3600,"avg_power_w":72.72,"max_power_w":72.72,"energy_kwh":0.07272,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-11T05:30:00Z","interval_end_utc":"2026-01-11T06:30:00Z","interval_seconds":3600,"avg_power_w":73.44,"max_power_w":73.44,"energy_kwh":0.07344,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-11T06:30:00Z","interval_end_utc":"2026-01-11T07:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  },
  "evaluation": {
    "window": {
      "start_utc": "2026-01-11T18:30:00Z",
      "end_utc": "2026-01-17T18:30:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-01-12T04:30:00Z","interval_end_utc":"2026-01-12T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-12T05:30:00Z","interval_end_utc":"2026-01-12T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-12T06:30:00Z","interval_end_utc":"2026-01-12T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-13T04:30:00Z","interval_end_utc":"2026-01-13T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-13T05:30:00Z","interval_end_utc":"2026-01-13T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-13T06:30:00Z","interval_end_utc":"2026-01-13T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-14T04:30:00Z","interval_end_utc":"2026-01-14T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-14T05:30:00Z","interval_end_utc":"2026-01-14T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-14T06:30:00Z","interval_end_utc":"2026-01-14T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-15T04:30:00Z","interval_end_utc":"2026-01-15T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-15T05:30:00Z","interval_end_utc":"2026-01-15T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-15T06:30:00Z","interval_end_utc":"2026-01-15T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-16T04:30:00Z","interval_end_utc":"2026-01-16T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-16T05:30:00Z","interval_end_utc":"2026-01-16T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-16T06:30:00Z","interval_end_utc":"2026-01-16T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-17T04:30:00Z","interval_end_utc":"2026-01-17T05:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-17T05:30:00Z","interval_end_utc":"2026-01-17T06:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-01-17T06:30:00Z","interval_end_utc":"2026-01-17T07:30:00Z","interval_seconds":3600,"occupancy_avg":4,"occupancy_max":4,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-12T04:30:00Z","interval_end_utc":"2026-01-12T05:30:00Z","interval_seconds":3600,"avg_power_w":70.56,"max_power_w":70.56,"energy_kwh":0.07056,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-12T05:30:00Z","interval_end_utc":"2026-01-12T06:30:00Z","interval_seconds":3600,"avg_power_w":71.28,"max_power_w":71.28,"energy_kwh":0.07128,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-12T06:30:00Z","interval_end_utc":"2026-01-12T07:30:00Z","interval_seconds":3600,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.072,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-13T04:30:00Z","interval_end_utc":"2026-01-13T05:30:00Z","interval_seconds":3600,"avg_power_w":74.398,"max_power_w":74.398,"energy_kwh":0.07439799999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-13T05:30:00Z","interval_end_utc":"2026-01-13T06:30:00Z","interval_seconds":3600,"avg_power_w":75.135,"max_power_w":75.135,"energy_kwh":0.075135,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-13T06:30:00Z","interval_end_utc":"2026-01-13T07:30:00Z","interval_seconds":3600,"avg_power_w":72.188,"max_power_w":72.188,"energy_kwh":0.072188,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-14T04:30:00Z","interval_end_utc":"2026-01-14T05:30:00Z","interval_seconds":3600,"avg_power_w":74.57,"max_power_w":74.57,"energy_kwh":0.07457,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-14T05:30:00Z","interval_end_utc":"2026-01-14T06:30:00Z","interval_seconds":3600,"avg_power_w":75.323,"max_power_w":75.323,"energy_kwh":0.075323,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-14T06:30:00Z","interval_end_utc":"2026-01-14T07:30:00Z","interval_seconds":3600,"avg_power_w":76.076,"max_power_w":76.076,"energy_kwh":0.07607599999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-15T04:30:00Z","interval_end_utc":"2026-01-15T05:30:00Z","interval_seconds":3600,"avg_power_w":78.524,"max_power_w":78.524,"energy_kwh":0.07852400000000001,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-15T05:30:00Z","interval_end_utc":"2026-01-15T06:30:00Z","interval_seconds":3600,"avg_power_w":75.445,"max_power_w":75.445,"energy_kwh":0.075445,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-15T06:30:00Z","interval_end_utc":"2026-01-15T07:30:00Z","interval_seconds":3600,"avg_power_w":76.215,"max_power_w":76.215,"energy_kwh":0.076215,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-16T04:30:00Z","interval_end_utc":"2026-01-16T05:30:00Z","interval_seconds":3600,"avg_power_w":78.646,"max_power_w":78.646,"energy_kwh":0.078646,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-16T05:30:00Z","interval_end_utc":"2026-01-16T06:30:00Z","interval_seconds":3600,"avg_power_w":79.433,"max_power_w":79.433,"energy_kwh":0.07943300000000002,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-16T06:30:00Z","interval_end_utc":"2026-01-16T07:30:00Z","interval_seconds":3600,"avg_power_w":80.219,"max_power_w":80.219,"energy_kwh":0.08021899999999998,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-17T04:30:00Z","interval_end_utc":"2026-01-17T05:30:00Z","interval_seconds":3600,"avg_power_w":78.702,"max_power_w":78.702,"energy_kwh":0.07870200000000001,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-17T05:30:00Z","interval_end_utc":"2026-01-17T06:30:00Z","interval_seconds":3600,"avg_power_w":79.505,"max_power_w":79.505,"energy_kwh":0.079505,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-01-17T06:30:00Z","interval_end_utc":"2026-01-17T07:30:00Z","interval_seconds":3600,"avg_power_w":80.308,"max_power_w":80.308,"energy_kwh":0.08030800000000002,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  }
}
```

### Insufficient-history case — response (HTTP 200)

```json
{
  "data": {
    "status": "insufficient_history",
    "findings": [],
    "other_changes": [],
    "devices": [
      {
        "device_id": "light-a",
        "room_id": "room-a",
        "device_type": "lighting",
        "status": "insufficient_history",
        "classification": null,
        "reason": "evaluation has 6 supported days over 6 days (coverage 1.00); needs 10 over 14 days with coverage >= 0.5",
        "context": "local hour",
        "resolution_seconds": 3600,
        "policy_ref": "pol-light-a:1",
        "reference_level_w": 72,
        "contexts_with_baseline": 3,
        "support": {
          "reference_days": 7,
          "evaluation_days": 6,
          "evaluation_span_days": 6,
          "reference_observations": 21,
          "evaluation_observations": 18
        },
        "excluded": {
          "reference": {},
          "evaluation": {}
        },
        "spike_days": []
      }
    ],
    "coverage": {
      "devices": 1,
      "evaluated": 0,
      "insufficient_history": 1,
      "unsupported_context": 0,
      "no_comparable_observations": 0,
      "reference_device_intervals": 21,
      "evaluation_device_intervals": 18
    },
    "exclusions": [],
    "warnings": [
      {
        "code": "NOT_AN_EFFICIENCY_DIAGNOSIS",
        "message": "A sustained upward power trend under matched observed conditions does not establish reduced efficiency or a fault: delivered output, outdoor conditions, setpoints and workload are not observed."
      },
      {
        "code": "NOT_ADDITIVE",
        "message": "Do not add trend magnitudes to vacancy or excess-consumption findings; they can overlap."
      }
    ],
    "detector": {
      "version": "gradual-power-trend-v1",
      "method": "rule",
      "technique": "theil_sen_context_normalised_daily",
      "request_format": "drift-request-v1",
      "model_used": false,
      "parameters": {
        "building_timezone": "Asia/Kolkata",
        "comfort_temp_bin_c": 1,
        "final_third_elevated_ratio": 1.05,
        "final_third_elevated_share": 0.75,
        "max_exclusions_listed": 200,
        "min_absolute_change_w": 10,
        "min_context_reference_days": 3,
        "min_day_observations": 3,
        "min_day_on_seconds": 3600,
        "min_evaluation_days": 10,
        "min_evaluation_day_coverage": 0.5,
        "min_evaluation_span_days": 14,
        "min_reference_days": 5,
        "min_reference_span_days": 7,
        "min_relative_change": 0.1,
        "offset_min_ratio": 1.1,
        "spike_ratio": 1.25,
        "step_max_within_segment": 0.03,
        "step_min_change": 0.1,
        "step_min_segment_days": 3
      }
    },
    "analysis": {
      "contract_version": "1.0.1",
      "dataset_id": "ds-synthetic-drift",
      "run_id": "run-synthetic-drift",
      "reference_window": {
        "start_utc": "2026-01-04T18:30:00Z",
        "end_utc": "2026-01-11T18:30:00Z"
      },
      "evaluation_window": {
        "start_utc": "2026-01-11T18:30:00Z",
        "end_utc": "2026-01-17T18:30:00Z"
      },
      "bounds": {
        "device_intervals_per_section": 2000,
        "room_intervals_per_section": 2000
      }
    }
  },
  "meta": {
    "request_id": "fc0a40db-09ea-483d-a2ab-eabeba74a0ed"
  }
}
```

## 6. Synthetic diagnostic (held-out; labels outside requests)

`.venv\Scripts\python.exe scripts\evaluate_drift_detector.py`

- **Seeds:** **9001–9020**, never used during development. Development used
  hand-built cases in `tests/test_drift.py` and smoke seed 1.
- **Case design:** 20 cases × 4 devices = 80 device series.
  - 14 reference and 28 evaluation days of hourly data (local 09–17);
  - **20 % of evaluation days missing**, 3 % missing hours, ±1.5 % noise;
  - an hour-dependent workstation load and a temperature-dependent AC.
- **Scenarios** (one random scenario per device):
  - gradual: +20–35 % over the period;
  - small: +2–5 %;
  - stable;
  - spike: one day ×1.5–2.0;
  - step: +20–40 % at a random day;
  - offset: +15–30 % from the start.
- **Parameters** were frozen before this ran.

```json
{
  "data": "SYNTHETIC (app.drift.synthetic.labelled_case); not real-building performance",
  "detector_version": "gradual-power-trend-v1",
  "seeds": [
    9001,
    9020
  ],
  "device_series": 80,
  "device_status_counts": {
    "evaluated": 80
  },
  "classification_by_label": {
    "gradual": {
      "sustained_upward_trend": 11
    },
    "offset": {
      "level_offset_without_trend": 16
    },
    "small": {
      "stable": 5
    },
    "spike": {
      "stable": 11
    },
    "stable": {
      "stable": 20
    },
    "step": {
      "abrupt_level_change": 17
    }
  },
  "excluded_intervals": {},
  "totals": {
    "tp": 11,
    "fp": 0,
    "fn_evaluated": 0,
    "fn_not_evaluated": 0,
    "precision": 1,
    "recall": 1
  }
}
```

- **Result:** every series was classified as its scenario intends. TP
  11, FP 0, FN 0; precision 1, recall 1.
  - Steps were all reported as `abrupt_level_change`, offsets as
    `level_offset_without_trend`, and spikes and small increases as
    `stable`.
- **Strong caveat:** these are **synthetic diagnostics only, not
  real-building performance**. The same author wrote the generator and the
  detector, and the scenarios are idealised: linear trends, perfectly flat
  steps, low noise, fully-on data only (hence no exclusions here; exclusion
  paths are covered by tests). Real equipment will be noisier and more
  ambiguous.

## 7. Tests and regressions

- **`tests/test_drift.py`** (23, all passing):
  - stable;
  - gradual +25 % is a finding with no significance, savings or ROI fields;
  - small +4 % is not;
  - a spike is not a trend (and is listed);
  - a step becomes `abrupt_level_change` at the right date;
  - an offset is `level_offset_without_trend`;
  - missing and irregular days aren't bridged, and < 50 % coverage gives
    `insufficient_history`;
  - a changed policy is excluded, giving `insufficient_history` or
    `unsupported_context`;
  - a hotter evaluation context for the AC gives no trend (contexts without a
    reference are excluded);
  - changing sampled hours (morning vs afternoon workstation load) gives no
    trend;
  - mixed duty is excluded;
  - group quantity has no effect;
  - insufficient reference or evaluation support is explicit;
  - duplicates don't inflate support;
  - the reference baseline is unaffected by evaluation values;
  - 6 validation cases (overlap, fault field, unknown device, wrong detector
    version, 2 × 413), conflicting duplicates and Infinity.
- **Full suite:** **153 passed**, including the unchanged `/v1/analyze`,
  `/v1/forecast` and `/v1/anomalies` tests. The 1 warning is Starlette's
  httpx notice.
- **Other checks:** pip check clean; check_env OK; contract verifier 75/75.
  There are no new dependencies.

## 8. Node (auditor-backend) integration guidance

1. **Choose periods:** from the auditor's own database, choose a **reference
   period** (normal operation) and a **later evaluation period** of at least
   14 days. They must not overlap.
2. **Send suitable data:** use hourly (or coarser) contract intervals, or a
   subset of devices/hours, so each section stays ≤ 2,000 device and ≤ 2,000
   room intervals. Include `on_fraction`, `partial` and `policy_ref`, plus
   room intervals with `avg_temp_c`/`occupancy_avg` for AC and refrigerators.
   Never zero-fill missing readings or send fault labels.
3. **Call and handle errors:** call `POST {ML_SERVICE_URL}/v1/drift`
   server-side. Handle 400 (`field`) and 413 (send fewer intervals; never
   expect Python to aggregate).
4. **Show:**
   - the overall and per-device `status`, `classification`, `reason` and
     `coverage`;
   - findings as "Sustained upward power trend under matched observed
     conditions", with the suggested investigation;
   - `other_changes` (step, offset, not sustained) as descriptive
     observations, not trends.
   Do **not** present findings as efficiency loss, faults or savings, and
   **do not sum** them with vacancy or excess-consumption results.

## 9. Limitations

- **Coverage:** fully-on observations only.
- **Context:** hour-of-day context for ordinary devices, and a coarse
  temperature bin plus occupancy for comfort equipment. Unobserved outdoor
  conditions, setpoints and workload remain confounders.
- **Configuration changes** are excluded conservatively, which can make
  devices `insufficient_history` or `unsupported_context`.
- **One fixed reference;** no seasonal adjustment.
- **Detectable magnitude:** an increase must reach ≥ 10 % and ≥ 10 W over
  the period with persistence. Slower or smaller drift is reported as
  stable.
- **Bounded requests** limit the temporal span per call; there is no
  multi-request stitching.
- **Evidence base:** synthetic only. Re-check on simulator/auditor data once
  it exists, via a separate, pre-registered evaluation.
