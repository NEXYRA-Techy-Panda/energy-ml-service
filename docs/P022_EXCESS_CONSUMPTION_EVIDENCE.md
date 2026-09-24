# P022_EXCESS_CONSUMPTION_EVIDENCE — excess-consumption deviation detector (M4)

> **Correction (P024, 2026-09-25).** Earlier wording said a temperature or
> occupancy change alone "never" produces a finding. That overstated it.
> Matching observed room temperature and occupancy reduces confounding, but it
> does not eliminate unmeasured differences such as outdoor temperature,
> setpoint or workload. Detector behaviour is unchanged.

Agent B — Claude Code | P022 | M4. Owner Mohan. Date 2026-09-24. Scope:
`energy-ml-service` only. Implementation is **completed**; review is
**pending**. The commit hash is reported in the P022 return report after the
push.

- **Starting state:** `ae23a61` (P021, accepted based on supplied evidence)
  equal to `origin/main`, with a clean tree.
- **Other models:** the P016 candidate remains offline, and production
  forecasting stays on P013.
- **What this is:** a **statistical reference detector**, not a trained model
  and not a diagnosis. `model_available` stays `false`.

## Endpoint (additive local API extension; shared contract unchanged)

`POST /v1/anomalies`, called server-side by auditor-backend only. It uses the
existing envelopes: success `{data, meta:{request_id}}` and error
`{error:{code, message, field?, row?}}`.

- **Request format** `excess-power-request-v1`:
  - `contract_version` (`"1.0.1"`), `dataset_id`, `run_id`;
  - `rooms[]`, `devices[]`, `policies[]`: the same closed models as
    `/v1/analyze`;
  - `reference{window{start_utc,end_utc}, room_intervals[], device_intervals[]}`:
    the **earlier** observations;
  - `evaluation{window{…}, room_intervals[], device_intervals[]}`: the
    **later** observations;
  - optional `detector{version}`, which must equal `"excess-power-mad-v1"`.
- **Interval records** reuse the contract-aligned `/v1/analyze` models.
  Required fields follow API Example A; the optional contract fields
  include `on_fraction`, `partial`, `avg_temp_c`, `occupancy_avg` and
  `max_power_w`.
- **The detector needs `on_fraction`** on device intervals, and needs room
  intervals (`avg_temp_c`, `occupancy_avg`) for comfort-dependent devices.
  Without them, intervals are excluded with a reason rather than guessed.

### Input limits and validation

- **Size limits:**
  - body ≤ **16 MiB**, else 413 `REQUEST_TOO_LARGE`;
  - **per section, independently:** ≤ **2,000 device intervals** and ≤
    **2,000 room intervals**, else 413, naming `reference.device_intervals`
    etc.
- **Separation:** `reference.window.end_utc` must be ≤
  `evaluation.window.start_utc` (else 400), so there is no future reference
  data. Every interval must lie inside its section's window.
- **Per section:** the **unchanged P010 semantic checks** run:
  - real timestamps, `end − start = interval_seconds`;
  - room/device/policy references resolve, and a policy may not be applied
    before its `effective_from`;
  - energy consistency (1e-9 kWh), max ≥ avg, durations ≤ interval;
  - no overlaps;
  - **identical duplicates deduplicated** (they cannot inflate reference
    support), **conflicting duplicates → 400**.
  Error fields carry the section prefix (e.g.
  `evaluation.device_intervals[0].energy_kwh`).
- **Always rejected:** NaN/Infinity, unknown fields, and injected-fault
  fields anywhere (e.g. `fault_active`) with 400. `expected.json` or labels
  are never inputs.

## Detection scope, comparability and thresholds (fixed before evaluation)

**Detector** `excess-power-mad-v1`. Response `method: "rule"`,
`technique: "robust_median_mad"`, finding type
`excess_consumption_deviation`.

**Comparability** (MVP: only clearly comparable, fully-on intervals):
1. Compare a device **only with its own** reference intervals. Never
   compare across devices, and never use a universal watt threshold.
2. Use **fully-on** intervals only (`on_fraction == 1`):
   - off intervals are excluded (`off`), because normal on/off switching is
     not excess;
   - mixed-duty intervals are excluded (`mixed_duty`) and **never divided by
     `on_fraction`**;
   - intervals with no `on_fraction` are excluded (`duty_unknown`);
   - `partial` intervals are excluded.
3. The same **interval resolution** (`interval_seconds`) is required.
4. **Group power semantics:** use the device's own reported `avg_power_w`,
   which is the whole device/group. It is **never multiplied by
   `quantity`**.
5. **Comfort-dependent equipment** (`ac`, `refrigerator`) is compared only
   with reference intervals whose room `avg_temp_c` is within **±1.0 °C**
   and `occupancy_avg` within **±1.0** of the evaluated interval.
   - Without room context the interval is excluded (`no_room_context`), and
     the device status is `unsupported_context`.
   - If there are too few comparable conditions, the result is
     `insufficient_reference` with the reason.
   - Matching observed context **reduces confounding but does not eliminate
     unmeasured differences** such as outdoor temperature, setpoint or
     workload. A hotter or busier room can still produce a finding when such
     unobserved factors differ (P024 correction; detector unchanged).
6. **Policy versions** change *when* a device runs, not its fully-on power,
   so they are not a comparability factor. Policy refs are still reported as
   evidence.
7. **Missing readings are absent, never zero.**

**Baseline and threshold** (reference section only; the evaluation section
never enters a baseline):
- **Minimum support:** **12** distinct comparable reference intervals
  spanning **≥ 2 h** (first start to last end).
- **Baseline:** median `m`; robust spread `s = 1.4826 × MAD`.
- **Threshold:** `m + max(4 × s, max(10 W, 10 % × m))`.
- **Zero MAD / constant reference:** the floor applies, so there is no
  division by zero, and `robust_z` is `null`.
- **Direction:** **upward** exceedances only.

**Findings** are contiguous flagged intervals per device, grouped. Each has:
- device, room and window;
- `observed` (mean and max W), `expected` (reference median W),
  `threshold_w`, `reference_support`;
- `deviation{watts, ratio, robust_z}`;
- `energy_above_baseline_kwh`, with `energy_note` saying it is **not** a
  guaranteed avoidable amount;
- `detector_version`, `assumptions`, `resolution_limit`, `suggested_action`
  (check schedule/manual state, connected load and equipment operation),
  and per-interval `evidence`.

Findings carry no confidence percentages and make no malfunction claim.

**Response honesty:**
- **Overall `status`:** `findings_detected`, `evaluated_no_deviation`,
  `insufficient_reference`, `unsupported_context` or
  `no_comparable_observations`.
- **Per-device status** uses the same set, with `deviation_found` in place
  of `findings_detected`.
- **`coverage`** counts evaluation intervals, evaluated, flagged and
  insufficient intervals, exclusions by reason, and reference usable and
  excluded intervals.
- **`exclusions[]`** lists up to 200 individual excluded observations
  (section, device, interval, reason), with `exclusions_total`.
- **Warnings:** `NOT_A_DIAGNOSIS` and `DRIFT_NOT_ANALYSED` are always
  present; `DUPLICATES_DEDUPED` appears when relevant.

Every valid request returns HTTP **200** with one of these statuses, so "no
findings" is never ambiguous.

## Live HTTP evidence (127.0.0.1:8000, SYNTHETIC requests)

- **Start command:** `.venv\Scripts\python.exe -m app`, with launcher PID
  12212 and interpreter PID 5940. Both were stopped afterwards and port 8000
  was free. **No process is left running.**
- **Regression checks** on the same server:
  - `POST /v1/analyze` (P010 fixture) → 200, one `light-a` finding (0.01 kWh
    avoidable), unchanged;
  - `POST /v1/forecast` (P013 synthetic request) → 200, 24 points,
    54.6749 kWh, `hourly-profile-median-v1`, unchanged;
  - `GET /health` → `model_available: false`;
  - `GET /v1/model/info` → `model_version: null`, baseline
    `hourly-profile-median-v1`, unchanged.

### Finding case — request

```json
{
  "contract_version": "1.0.1",
  "dataset_id": "ds-synthetic-anomaly",
  "run_id": "run-synthetic-anomaly",
  "rooms": [
    {"room_id":"room-a","name":"Room A","capacity":12},
    {"room_id":"room-b","name":"Room B","capacity":4}
  ],
  "devices": [
    {"device_id":"light-a","name":"Room A light","room_id":"room-a","device_type":"lighting","always_on":false,"quantity":1,"nominal_power_w":72,"standby_power_w":0,"control":"scheduled"}
  ],
  "policies": [
    {
      "policy_id": "pol-hours",
      "version": 1,
      "kind": "office_hours",
      "rules": {
        "working_days_iso": [
          1,
          2,
          3,
          4,
          5
        ],
        "open_local": "09:00",
        "close_local": "18:00",
        "overnight": false
      }
    },
    {
      "policy_id": "pol-light-a",
      "version": 1,
      "kind": "lighting_schedule",
      "rules": {
        "on_during_hours": true,
        "vacancy_grace_seconds": 300
      }
    }
  ],
  "reference": {
    "window": {
      "start_utc": "2026-03-02T00:00:00Z",
      "end_utc": "2026-03-02T02:00:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:00:00Z","interval_end_utc":"2026-03-02T00:05:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:05:00Z","interval_end_utc":"2026-03-02T00:10:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:10:00Z","interval_end_utc":"2026-03-02T00:15:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:15:00Z","interval_end_utc":"2026-03-02T00:20:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:20:00Z","interval_end_utc":"2026-03-02T00:25:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:25:00Z","interval_end_utc":"2026-03-02T00:30:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:30:00Z","interval_end_utc":"2026-03-02T00:35:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:35:00Z","interval_end_utc":"2026-03-02T00:40:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:40:00Z","interval_end_utc":"2026-03-02T00:45:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:45:00Z","interval_end_utc":"2026-03-02T00:50:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:50:00Z","interval_end_utc":"2026-03-02T00:55:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:55:00Z","interval_end_utc":"2026-03-02T01:00:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:00:00Z","interval_end_utc":"2026-03-02T01:05:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:05:00Z","interval_end_utc":"2026-03-02T01:10:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:10:00Z","interval_end_utc":"2026-03-02T01:15:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:15:00Z","interval_end_utc":"2026-03-02T01:20:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:20:00Z","interval_end_utc":"2026-03-02T01:25:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:25:00Z","interval_end_utc":"2026-03-02T01:30:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:30:00Z","interval_end_utc":"2026-03-02T01:35:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:35:00Z","interval_end_utc":"2026-03-02T01:40:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:40:00Z","interval_end_utc":"2026-03-02T01:45:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:45:00Z","interval_end_utc":"2026-03-02T01:50:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:50:00Z","interval_end_utc":"2026-03-02T01:55:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T01:55:00Z","interval_end_utc":"2026-03-02T02:00:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:00:00Z","interval_end_utc":"2026-03-02T00:05:00Z","interval_seconds":300,"avg_power_w":71.424,"max_power_w":71.424,"energy_kwh":0.005952,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:05:00Z","interval_end_utc":"2026-03-02T00:10:00Z","interval_seconds":300,"avg_power_w":71.712,"max_power_w":71.712,"energy_kwh":0.005976,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:10:00Z","interval_end_utc":"2026-03-02T00:15:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:15:00Z","interval_end_utc":"2026-03-02T00:20:00Z","interval_seconds":300,"avg_power_w":72.288,"max_power_w":72.288,"energy_kwh":0.006023999999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:20:00Z","interval_end_utc":"2026-03-02T00:25:00Z","interval_seconds":300,"avg_power_w":72.576,"max_power_w":72.576,"energy_kwh":0.0060479999999999996,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:25:00Z","interval_end_utc":"2026-03-02T00:30:00Z","interval_seconds":300,"avg_power_w":71.424,"max_power_w":71.424,"energy_kwh":0.005952,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:30:00Z","interval_end_utc":"2026-03-02T00:35:00Z","interval_seconds":300,"avg_power_w":71.712,"max_power_w":71.712,"energy_kwh":0.005976,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:35:00Z","interval_end_utc":"2026-03-02T00:40:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:40:00Z","interval_end_utc":"2026-03-02T00:45:00Z","interval_seconds":300,"avg_power_w":72.288,"max_power_w":72.288,"energy_kwh":0.006023999999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:45:00Z","interval_end_utc":"2026-03-02T00:50:00Z","interval_seconds":300,"avg_power_w":72.576,"max_power_w":72.576,"energy_kwh":0.0060479999999999996,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:50:00Z","interval_end_utc":"2026-03-02T00:55:00Z","interval_seconds":300,"avg_power_w":71.424,"max_power_w":71.424,"energy_kwh":0.005952,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:55:00Z","interval_end_utc":"2026-03-02T01:00:00Z","interval_seconds":300,"avg_power_w":71.712,"max_power_w":71.712,"energy_kwh":0.005976,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:00:00Z","interval_end_utc":"2026-03-02T01:05:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:05:00Z","interval_end_utc":"2026-03-02T01:10:00Z","interval_seconds":300,"avg_power_w":72.288,"max_power_w":72.288,"energy_kwh":0.006023999999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:10:00Z","interval_end_utc":"2026-03-02T01:15:00Z","interval_seconds":300,"avg_power_w":72.576,"max_power_w":72.576,"energy_kwh":0.0060479999999999996,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:15:00Z","interval_end_utc":"2026-03-02T01:20:00Z","interval_seconds":300,"avg_power_w":71.424,"max_power_w":71.424,"energy_kwh":0.005952,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:20:00Z","interval_end_utc":"2026-03-02T01:25:00Z","interval_seconds":300,"avg_power_w":71.712,"max_power_w":71.712,"energy_kwh":0.005976,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:25:00Z","interval_end_utc":"2026-03-02T01:30:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:30:00Z","interval_end_utc":"2026-03-02T01:35:00Z","interval_seconds":300,"avg_power_w":72.288,"max_power_w":72.288,"energy_kwh":0.006023999999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:35:00Z","interval_end_utc":"2026-03-02T01:40:00Z","interval_seconds":300,"avg_power_w":72.576,"max_power_w":72.576,"energy_kwh":0.0060479999999999996,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:40:00Z","interval_end_utc":"2026-03-02T01:45:00Z","interval_seconds":300,"avg_power_w":71.424,"max_power_w":71.424,"energy_kwh":0.005952,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:45:00Z","interval_end_utc":"2026-03-02T01:50:00Z","interval_seconds":300,"avg_power_w":71.712,"max_power_w":71.712,"energy_kwh":0.005976,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:50:00Z","interval_end_utc":"2026-03-02T01:55:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T01:55:00Z","interval_end_utc":"2026-03-02T02:00:00Z","interval_seconds":300,"avg_power_w":72.288,"max_power_w":72.288,"energy_kwh":0.006023999999999999,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  },
  "evaluation": {
    "window": {
      "start_utc": "2026-03-02T02:00:00Z",
      "end_utc": "2026-03-02T02:20:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-03-02T02:00:00Z","interval_end_utc":"2026-03-02T02:05:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T02:05:00Z","interval_end_utc":"2026-03-02T02:10:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T02:10:00Z","interval_end_utc":"2026-03-02T02:15:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T02:15:00Z","interval_end_utc":"2026-03-02T02:20:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T02:00:00Z","interval_end_utc":"2026-03-02T02:05:00Z","interval_seconds":300,"avg_power_w":72.2,"max_power_w":72.2,"energy_kwh":0.006016666666666667,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T02:05:00Z","interval_end_utc":"2026-03-02T02:10:00Z","interval_seconds":300,"avg_power_w":104.5,"max_power_w":104.5,"energy_kwh":0.008708333333333334,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T02:10:00Z","interval_end_utc":"2026-03-02T02:15:00Z","interval_seconds":300,"avg_power_w":105.1,"max_power_w":105.1,"energy_kwh":0.008758333333333333,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T02:15:00Z","interval_end_utc":"2026-03-02T02:20:00Z","interval_seconds":300,"avg_power_w":36,"max_power_w":36,"energy_kwh":0.003,"on_fraction":0.5,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  },
  "detector": {
    "version": "excess-power-mad-v1"
  }
}
```

### Finding case — response (HTTP 200)

```json
{
  "data": {
    "status": "findings_detected",
    "findings": [
      {
        "finding_id": "excess_consumption_deviation:light-a:2026-03-02T02:05:00Z",
        "finding_type": "excess_consumption_deviation",
        "device_id": "light-a",
        "room_id": "room-a",
        "window_start_utc": "2026-03-02T02:05:00Z",
        "window_end_utc": "2026-03-02T02:15:00Z",
        "intervals": 2,
        "observed": {
          "value": 104.8,
          "unit": "W",
          "statistic": "mean avg_power_w over flagged intervals",
          "max": 105.1
        },
        "expected": {
          "value": 72,
          "unit": "W",
          "statistic": "reference median power"
        },
        "threshold_w": 82,
        "reference_support": 24,
        "deviation": {
          "watts": 32.8,
          "ratio": 1.4555555555555555,
          "robust_z": 76.8170031626131
        },
        "energy_above_baseline_kwh": 0.0054666666666666665,
        "energy_note": "Energy above the reference median over the flagged intervals; NOT a guaranteed avoidable amount.",
        "method": "rule",
        "technique": "robust_median_mad",
        "detector_version": "excess-power-mad-v1",
        "suggested_action": "Check the Room A light in Room A: confirm its schedule/manual state, connected load and equipment operation during this window.",
        "assumptions": "Compared only with this device's own fully-on reference intervals at 300-second resolution (reference 2026-03-02T00:00:00Z to 2026-03-02T02:00:00Z). Power is the device's reported whole-device/group average power; quantity is not applied. Threshold = reference median + max(4 × 1.4826 × MAD, max(10 W, 10% of median)). A power deviation alone does not establish a malfunction, voltage fault or efficiency loss.",
        "resolution_limit": "300-second interval averages; sub-interval spikes and duty patterns are not visible.",
        "evidence": {
          "policy_refs": [
            "pol-light-a:1"
          ],
          "intervals": [
            {
              "interval_start_utc": "2026-03-02T02:05:00Z",
              "avg_power_w": 104.5,
              "expected_w": 72,
              "threshold_w": 82,
              "reference_support": 24
            },
            {
              "interval_start_utc": "2026-03-02T02:10:00Z",
              "avg_power_w": 105.1,
              "expected_w": 72,
              "threshold_w": 82,
              "reference_support": 24
            }
          ],
          "flagged_seconds": 600
        }
      }
    ],
    "devices": [
      {
        "device_id": "light-a",
        "room_id": "room-a",
        "device_type": "lighting",
        "status": "deviation_found",
        "comparison": "own fully-on reference",
        "reference": {
          "usable_intervals": 24,
          "excluded": {},
          "baselines_by_interval_seconds": {
            "300": {
              "support": 24,
              "span_hours": 2,
              "median_w": 72,
              "mad_w": 0.2879999999999967,
              "robust_sigma_w": 0.42698879999999506,
              "threshold_w": 82
            }
          }
        },
        "evaluation": {
          "evaluated": 3,
          "flagged": 2,
          "insufficient_reference": 0,
          "insufficient_reasons": {},
          "excluded": {
            "mixed_duty": 1
          }
        }
      }
    ],
    "coverage": {
      "evaluation_device_intervals": 4,
      "evaluated": 3,
      "flagged": 2,
      "insufficient_reference": 0,
      "excluded": {
        "mixed_duty": 1
      },
      "reference_device_intervals": 24,
      "reference_usable": 24,
      "reference_excluded": {}
    },
    "exclusions": [
      {
        "section": "evaluation",
        "device_id": "light-a",
        "interval_start_utc": "2026-03-02T02:15:00Z",
        "reason": "mixed_duty"
      }
    ],
    "exclusions_listed": 1,
    "exclusions_total": 1,
    "warnings": [
      {
        "code": "NOT_A_DIAGNOSIS",
        "message": "Findings are statistical excess-consumption deviations versus the device's own earlier comparable operation; they do not confirm a malfunction, voltage fault or efficiency loss."
      },
      {
        "code": "DRIFT_NOT_ANALYSED",
        "message": "Gradual deterioration (trend/drift) is not detected by this detector; it compares intervals with a fixed earlier reference only."
      }
    ],
    "detector": {
      "version": "excess-power-mad-v1",
      "method": "rule",
      "technique": "robust_median_mad",
      "request_format": "excess-power-request-v1",
      "parameters": {
        "min_reference_support": 12,
        "min_reference_span_hours": 2,
        "mad_scale": 1.4826,
        "threshold_k": 4,
        "abs_floor_w": 10,
        "rel_floor": 0.1,
        "comfort_dependent_types": [
          "ac",
          "refrigerator"
        ],
        "temp_band_c": 1,
        "occupancy_band": 1,
        "fully_on_only": true,
        "max_exclusions_listed": 200
      },
      "model_used": false
    },
    "analysis": {
      "contract_version": "1.0.1",
      "dataset_id": "ds-synthetic-anomaly",
      "run_id": "run-synthetic-anomaly",
      "reference_window": {
        "start_utc": "2026-03-02T00:00:00Z",
        "end_utc": "2026-03-02T02:00:00Z"
      },
      "evaluation_window": {
        "start_utc": "2026-03-02T02:00:00Z",
        "end_utc": "2026-03-02T02:20:00Z"
      },
      "bounds": {
        "device_intervals_per_section": 2000,
        "room_intervals_per_section": 2000
      }
    }
  },
  "meta": {
    "request_id": "d807b943-324d-4b61-9bde-d5c73cbf4ad2"
  }
}
```

### Insufficient-history case — request

```json
{
  "contract_version": "1.0.1",
  "dataset_id": "ds-synthetic-anomaly",
  "run_id": "run-synthetic-anomaly",
  "rooms": [
    {"room_id":"room-a","name":"Room A","capacity":12},
    {"room_id":"room-b","name":"Room B","capacity":4}
  ],
  "devices": [
    {"device_id":"light-a","name":"Room A light","room_id":"room-a","device_type":"lighting","always_on":false,"quantity":1,"nominal_power_w":72,"standby_power_w":0,"control":"scheduled"}
  ],
  "policies": [
    {
      "policy_id": "pol-hours",
      "version": 1,
      "kind": "office_hours",
      "rules": {
        "working_days_iso": [
          1,
          2,
          3,
          4,
          5
        ],
        "open_local": "09:00",
        "close_local": "18:00",
        "overnight": false
      }
    },
    {
      "policy_id": "pol-light-a",
      "version": 1,
      "kind": "lighting_schedule",
      "rules": {
        "on_during_hours": true,
        "vacancy_grace_seconds": 300
      }
    }
  ],
  "reference": {
    "window": {
      "start_utc": "2026-03-02T00:00:00Z",
      "end_utc": "2026-03-02T00:30:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:00:00Z","interval_end_utc":"2026-03-02T00:05:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:05:00Z","interval_end_utc":"2026-03-02T00:10:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:10:00Z","interval_end_utc":"2026-03-02T00:15:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:15:00Z","interval_end_utc":"2026-03-02T00:20:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:20:00Z","interval_end_utc":"2026-03-02T00:25:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:25:00Z","interval_end_utc":"2026-03-02T00:30:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:00:00Z","interval_end_utc":"2026-03-02T00:05:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:05:00Z","interval_end_utc":"2026-03-02T00:10:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:10:00Z","interval_end_utc":"2026-03-02T00:15:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:15:00Z","interval_end_utc":"2026-03-02T00:20:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:20:00Z","interval_end_utc":"2026-03-02T00:25:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:25:00Z","interval_end_utc":"2026-03-02T00:30:00Z","interval_seconds":300,"avg_power_w":72,"max_power_w":72,"energy_kwh":0.006,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  },
  "evaluation": {
    "window": {
      "start_utc": "2026-03-02T00:30:00Z",
      "end_utc": "2026-03-02T00:40:00Z"
    },
    "room_intervals": [
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:30:00Z","interval_end_utc":"2026-03-02T00:35:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55},
      {"room_id":"room-a","interval_start_utc":"2026-03-02T00:35:00Z","interval_end_utc":"2026-03-02T00:40:00Z","interval_seconds":300,"occupancy_avg":2,"occupancy_max":2,"occupied_fraction":1,"avg_temp_c":25,"avg_rh_pct":55}
    ],
    "device_intervals": [
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:30:00Z","interval_end_utc":"2026-03-02T00:35:00Z","interval_seconds":300,"avg_power_w":110,"max_power_w":110,"energy_kwh":0.009166666666666667,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"},
      {"device_id":"light-a","room_id":"room-a","interval_start_utc":"2026-03-02T00:35:00Z","interval_end_utc":"2026-03-02T00:40:00Z","interval_seconds":300,"avg_power_w":110,"max_power_w":110,"energy_kwh":0.009166666666666667,"on_fraction":1,"vacant_on_seconds":0,"offschedule_on_seconds":0,"policy_ref":"pol-light-a:1"}
    ]
  }
}
```

### Insufficient-history case — response (HTTP 200)

```json
{
  "data": {
    "status": "insufficient_reference",
    "findings": [],
    "devices": [
      {
        "device_id": "light-a",
        "room_id": "room-a",
        "device_type": "lighting",
        "status": "insufficient_reference",
        "comparison": "own fully-on reference",
        "reference": {
          "usable_intervals": 6,
          "excluded": {},
          "baselines_by_interval_seconds": {
            "300": {
              "insufficient": "6 comparable reference intervals (needs 12)"
            }
          }
        },
        "evaluation": {
          "evaluated": 0,
          "flagged": 0,
          "insufficient_reference": 2,
          "insufficient_reasons": {
            "6 comparable reference intervals (needs 12)": 2
          },
          "excluded": {}
        }
      }
    ],
    "coverage": {
      "evaluation_device_intervals": 2,
      "evaluated": 0,
      "flagged": 0,
      "insufficient_reference": 2,
      "excluded": {},
      "reference_device_intervals": 6,
      "reference_usable": 6,
      "reference_excluded": {}
    },
    "exclusions": [],
    "exclusions_listed": 0,
    "exclusions_total": 0,
    "warnings": [
      {
        "code": "NOT_A_DIAGNOSIS",
        "message": "Findings are statistical excess-consumption deviations versus the device's own earlier comparable operation; they do not confirm a malfunction, voltage fault or efficiency loss."
      },
      {
        "code": "DRIFT_NOT_ANALYSED",
        "message": "Gradual deterioration (trend/drift) is not detected by this detector; it compares intervals with a fixed earlier reference only."
      }
    ],
    "detector": {
      "version": "excess-power-mad-v1",
      "method": "rule",
      "technique": "robust_median_mad",
      "request_format": "excess-power-request-v1",
      "parameters": {
        "min_reference_support": 12,
        "min_reference_span_hours": 2,
        "mad_scale": 1.4826,
        "threshold_k": 4,
        "abs_floor_w": 10,
        "rel_floor": 0.1,
        "comfort_dependent_types": [
          "ac",
          "refrigerator"
        ],
        "temp_band_c": 1,
        "occupancy_band": 1,
        "fully_on_only": true,
        "max_exclusions_listed": 200
      },
      "model_used": false
    },
    "analysis": {
      "contract_version": "1.0.1",
      "dataset_id": "ds-synthetic-anomaly",
      "run_id": "run-synthetic-anomaly",
      "reference_window": {
        "start_utc": "2026-03-02T00:00:00Z",
        "end_utc": "2026-03-02T00:30:00Z"
      },
      "evaluation_window": {
        "start_utc": "2026-03-02T00:30:00Z",
        "end_utc": "2026-03-02T00:40:00Z"
      },
      "bounds": {
        "device_intervals_per_section": 2000,
        "room_intervals_per_section": 2000
      }
    }
  },
  "meta": {
    "request_id": "9700306e-b179-40c6-888a-d09b67460717"
  }
}
```

## Synthetic detection evaluation (held-out; labels separate from inputs)

`.venv\Scripts\python.exe scripts\evaluate_excess_detector.py`

- **Cases:** `app/anomalies/synthetic.py` `labelled_case(seed)` for held-out
  seeds **7001–7005**. They were fixed in advance; seed 1 was used only for a
  development smoke check.
- **Case design:**
  - 300 reference and 300 evaluation 5-minute intervals per device;
  - lights and workstations on in a daytime block with mixed-duty edges;
  - an AC whose demand rises with room temperature, plus a heat spell in
    the evaluation period;
  - a constant refrigerator;
  - a ×5 reference spike per device;
  - 2 % missing readings;
  - **two strong (+35 %) and one subtle (+6 %) injected excess blocks** of
    12 intervals each.
- **Labels** are returned separately and never sent.
- **Parameters** were frozen before this ran.
- **Unit:** one (device, 5-minute interval).
- **Provenance:** SYNTHETIC diagnostics, **not real-building accuracy**. The
  same author wrote the generator and the detector, so zero false positives
  on these simple patterns proves little about real data.

```json
{
  "data": "SYNTHETIC (app.anomalies.synthetic.labelled_case); not real-building accuracy",
  "detector_version": "excess-power-mad-v1",
  "seeds": [
    7001,
    7002,
    7003,
    7004,
    7005
  ],
  "per_seed": [
    {
      "seed": 7001,
      "status": "findings_detected",
      "labels": 36,
      "tp": 22,
      "fp": 0,
      "fn_evaluated": 11,
      "fn_not_evaluated": 3,
      "strong_detected": "22/24",
      "subtle_detected": "0/12",
      "evaluation_intervals": 1177,
      "evaluated": 613,
      "excluded": 564,
      "insufficient_reference": 0,
      "findings": 4
    },
    {
      "seed": 7002,
      "status": "findings_detected",
      "labels": 36,
      "tp": 23,
      "fp": 0,
      "fn_evaluated": 11,
      "fn_not_evaluated": 2,
      "strong_detected": "23/24",
      "subtle_detected": "0/12",
      "evaluation_intervals": 1169,
      "evaluated": 605,
      "excluded": 564,
      "insufficient_reference": 0,
      "findings": 3
    },
    {
      "seed": 7003,
      "status": "findings_detected",
      "labels": 36,
      "tp": 24,
      "fp": 0,
      "fn_evaluated": 12,
      "fn_not_evaluated": 0,
      "strong_detected": "24/24",
      "subtle_detected": "0/12",
      "evaluation_intervals": 1176,
      "evaluated": 616,
      "excluded": 560,
      "insufficient_reference": 0,
      "findings": 2
    },
    {
      "seed": 7004,
      "status": "findings_detected",
      "labels": 36,
      "tp": 23,
      "fp": 0,
      "fn_evaluated": 12,
      "fn_not_evaluated": 1,
      "strong_detected": "23/24",
      "subtle_detected": "0/12",
      "evaluation_intervals": 1174,
      "evaluated": 612,
      "excluded": 562,
      "insufficient_reference": 0,
      "findings": 3
    },
    {
      "seed": 7005,
      "status": "findings_detected",
      "labels": 36,
      "tp": 24,
      "fp": 0,
      "fn_evaluated": 12,
      "fn_not_evaluated": 0,
      "strong_detected": "24/24",
      "subtle_detected": "0/12",
      "evaluation_intervals": 1180,
      "evaluated": 611,
      "excluded": 569,
      "insufficient_reference": 0,
      "findings": 2
    }
  ],
  "totals": {
    "tp": 116,
    "fp": 0,
    "fn_evaluated": 58,
    "fn_not_evaluated": 6,
    "labels": 180,
    "evaluated": 3057,
    "excluded": 2819,
    "insufficient": 0,
    "evaluation_intervals": 5876,
    "strong_recall": 0.9667,
    "subtle_recall": 0,
    "precision": 1,
    "recall": 0.6444,
    "recall_among_evaluated_labels": 0.6667
  }
}
```

- **Totals:**
  - TP 116, FP 0, FN 64 (58 evaluated but below
    threshold; 6 not evaluated because the reading was missing or
    the interval excluded);
  - precision 1, recall 0.6444;
  - strong-injection recall 0.9667; subtle (+6 %) recall 0.
- **Why the subtle injections are missed:** a +6 % change (about 4 W on a
  72 W light, about 9 W on a 150 W fridge, about 58 W on 960 W workstations)
  is below the fixed floor of max(10 W, 10 %) plus 4 robust σ. This is
  expected **by design**, not a bug.
- **No false alarms** on these synthetic cases (where context was fully
  observed by construction; real rooms have unobserved factors) from:
  - the heat-spell AC (conditional comparison);
  - reference spikes (the median is robust);
  - on/off switching;
  - mixed-duty edges (excluded).

## Tests (`tests/test_anomalies.py`, 24; full suite 130 passed)

- **Detection behaviour:**
  - stable operation gives no finding, with coverage reported;
  - a large increase is a finding, labelled a deviation, with no
    confidence/avoidable claims;
  - constant reference: MAD 0 → floor threshold 82 W, no division by zero,
    `robust_z` null; +8 W not flagged, +18 W flagged;
  - on/off changes are excluded as `off`;
  - mixed duty is excluded and never divided;
  - AC in a hotter room gives `insufficient_reference`, not a finding; in
    the same conditions a +31 % increase is flagged;
  - no room context gives `unsupported_context`;
  - insufficient support (5 < 12) and span (1.67 h < 2 h) are explicit;
  - a ×10 reference outlier doesn't move the median;
  - missing readings are not zero;
  - changing evaluation data leaves the reference baseline identical;
  - the workstation group baseline is about 960 W and changing `quantity`
    changes nothing;
  - an all-off evaluation gives `no_comparable_observations` with coverage 0
    evaluated.
- **Validation:**
  - a reference window overlapping the evaluation gives 400;
  - fault field, unknown device, energy inconsistency, impossible date,
    detector version and contract version are all rejected with the exact
    prefixed field;
  - 2,001 reference device intervals and 2,001 evaluation room intervals
    give 413;
  - identical duplicates don't inflate support; conflicting ones give 400;
  - NaN gives 400.

Other checks: pip check clean; check_env OK; contract verifier 75/75. The
existing `/v1/analyze` (37) and `/v1/forecast` (37) tests pass unchanged.

## Auditor-backend integration (later, Node, server-side)

1. **Choose periods:** from its own database, pick an **earlier reference
   period** (normal operation, same run/dataset) and a **later evaluation
   period**. The reference must end at or before the evaluation starts.
   Send ≤ 2,000 device and ≤ 2,000 room intervals per section, and window
   longer periods.
2. **Send the data:** include `on_fraction`, `partial`, and room intervals
   with `avg_temp_c` and `occupancy_avg`. Contract exports already carry
   these. Never add or zero-fill missing readings, and never send fault
   labels.
3. **Call:** `POST {ML_SERVICE_URL}/v1/anomalies`. Handle 400 (fix `field`)
   and 413 (fewer intervals).
4. **Show the result:**
   - show `status`, `coverage` and per-device statuses, so "no findings"
     isn't confused with "nothing evaluated";
   - show findings as **excess-consumption deviations** with
     observed/expected/threshold and the suggested checks;
   - do **not** present `energy_above_baseline_kwh` as avoidable savings,
     and do not present findings as malfunctions.
5. **Keep it separate:** this is independent of `/v1/analyze`'s vacancy rule.
   The two findings can overlap in time.

## Limitations and remaining work

- **Scope:**
  - fully-on intervals only (mixed duty and duty-unknown are excluded);
  - comfort conditioning is by temperature and occupancy bands only
    (no humidity, weather or setpoint);
  - one fixed reference per request.
- **Not implemented:**
  - **Gradual deterioration / drift** needs a separate temporal trend
    analysis (e.g. robust slope over rolling references).
  - Spike detection within an interval is not possible from interval
    averages.
- **Sensitivity:** changes smaller than max(10 W, 10 %) plus 4 robust σ are
  not detected by design.
- **Evidence base:** synthetic evaluation only. Parameters should be
  re-checked on simulator exports once available, via a separate,
  pre-registered evaluation.
