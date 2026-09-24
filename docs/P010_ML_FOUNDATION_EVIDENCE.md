# P010_ML_FOUNDATION_EVIDENCE — deterministic analysis baseline

Assignment P010 (ML foundation part). Agent B (Claude Code); owner Mohan;
2026-09-24. Scope: `energy-ml-service`. Implementation is **completed**;
review is **pending**. The commit hash is reported in the P010 return report
after the push.

## Starting state

- No `AGENTS.md`. `main` was at `22b0a08` (F2-B), equal to `origin/main`,
  with a clean tree.
- Contract 1.0.1 is unchanged: `node scripts/verify-contract.mjs` gives
  75/75, including manifest hashes.
- No new dependencies. The route uses the existing pinned FastAPI and
  pydantic; nothing was installed.

## What was implemented

- **`POST /v1/analyze`** is a **deterministic rule baseline** (`method: "rule"`).
  - It is not a trained model and returns no probabilities.
  - `model_available` stays `false` and `/v1/model/info` versions stay `null`.
  - The route works without a model, so it never returns
    `MODEL_UNAVAILABLE` just because none exists.
  - `/v1/forecast` is still not implemented (404).
- **Request:** inline bounded data only, as in API.md Example A:
  - version, dataset/run identity, window;
  - room, device and policy metadata;
  - room and device interval arrays;
  - options.
  There is no database, no file references, no callbacks and no browser
  access.
- **Code:**
  - `app/analysis/models.py`: closed, strict pydantic models, with contract
    `$defs` for the per-kind policy rules.
  - `app/analysis/validate.py`: parsing order and semantic checks.
  - `app/analysis/rules.py`: the rule.
  - `app/analysis/service.py`: the response.
  - `app/errors.py`: the contract error envelope.

### Validation (all failures use the contract error envelope with `field`)

1. **Body and version:**
   - a body over 8 MiB returns 413;
   - invalid JSON returns 400;
   - a missing `contract_version` returns 400; a version other than
     `1.0.1` returns 400 `UNSUPPORTED_VERSION`.
2. **Record bounds:** more than **2,000 device intervals** or more than
   **2,000 room intervals** returns **413 `REQUEST_TOO_LARGE`**, naming the
   bound. Exactly 2,000 is accepted.
3. **Forbidden fields:** injected-fault fields anywhere, including nested
   rules and options, return 400. The list is `fault_active`, `fault_type`,
   `fault_window(s)`, `injected_fault`, `expected_diagnosis`,
   `expected_finding`, `is_fault` and `fault_label`.
4. **Closed models:**
   - unknown fields, contract bounds, id/UTC/`HH:MM`/`policy_ref` patterns;
   - kind-specific rules, with defaults applied: `device_schedule` grace 300,
     `on_windows []`.
5. **Semantics:**
   - timestamps must be real calendar times;
   - the window must have start < end; intervals must lie inside it;
   - `end − start = interval_seconds`;
   - interval `run_id` must equal the request's;
   - unique room, device and policy versions;
   - device→room references; device interval room = device room;
   - `policy_ref` must resolve; `applies_to` must name a known
     device/room/building and match the interval's device;
     `office_hours_ref` must point to office_hours;
   - **a policy version with `effective_from_utc` after the interval start
     is rejected** (never applied retroactively);
   - `|energy_kwh − avg_power_w × s / 3.6e6| ≤ 1e-9`; max ≥ avg;
   - durations ≤ interval; vacant-on ≤ on-time;
   - room occupancy is consistent;
   - no overlapping intervals per room/device.
6. **Duplicates:** identical duplicates are deduplicated and reported with a
   warning. Conflicting duplicates return 400. No invalid record is dropped
   silently.

### Rule `vacant-beyond-grace-v1` (`finding_type: "vacant_but_on"`)

"An eligible device operated while its room was vacant beyond its vacancy
grace."

- **Eligible devices:** those whose applied policy is `lighting_schedule` or
  `device_schedule`. **Always-on exceptions** (device `always_on` or an
  `always_on` policy) are excluded and listed in
  `analysis.excluded_devices`.
- **Vacancy:** a room interval counts as fully vacant only when
  `occupancy_max = 0`. **Mixed intervals are never treated as vacant.** If
  the device ran in one, a `MIXED_OCCUPANCY` warning is returned and no
  finding.
- **Vacancy start:** the start of the earliest contiguous fully vacant room
  interval. This is a **lower bound**, so waste is never overstated. When
  the vacant run reaches the start of the supplied data or a gap, the
  service does **not** assume the room was already vacant for the grace
  period. It counts only operation after the provable expiry and adds an
  `INSUFFICIENT_VACANCY_CONTEXT` warning.
- **Grace:** it comes from the policy version each interval references (the
  version actually applied). **Zero grace** makes a fully vacant interval
  count at once.
- **Avoidable energy** is estimated only when supported:
  - the device's `standby_power_w` is known; and
  - either the whole interval is beyond grace, or the device was on for the
    whole interval (constant-power assumption, stated in `assumptions`).
  Otherwise the finding reports observed operating seconds and no estimate.
  A partly-on interval that straddles expiry gets a `SUB_INTERVAL_TIMING`
  warning.
- **Finding values:**
  - `observed` = the device's energy in the counted time;
  - `expected` = its standby energy over the same time;
  - `avoidable_energy_kwh` = the difference;
  - `avoidable_cost_inr` only when `options.tariff_inr_per_kwh` is given.
- **Overrides:** manual overrides are **described** in `assumptions`, not
  judged.
- **Always-on warning:** every response includes `ANALYSES_NOT_PERFORMED`.
  No drift, spike, anomaly-model or forecast analysis is fabricated.

### Response additions beyond contract 1.0.1

- **Contract shape:** `{findings, warnings}` plus the finding fields.
- **Additions:**
  - `finding.evidence`: rule version, policy refs, per-interval evidence;
  - `finding.avoidable_cost_inr`: the contract §8 "when supported" field;
  - `warnings[]` objects: `{code, message, device_id?, room_id?, window_*?}`;
  - `analysis`: contract version, identity, window, `method: "rule"`,
    `model_used: false`, record counts and bounds, excluded devices.
- `assumptions` and `resolution_limit` are strings, matching the fixture
  oracle.

### Bounds and temporal context

At most 2,000 device intervals and 2,000 room intervals per request. For the
18-device MVP office at one-minute resolution, that is about **111 minutes of
data per request** (2,000 ÷ 18). **A whole month cannot be analysed in one
request.** The later auditor orchestration must split the period into
windows and **include preceding context** (the vacancy run before each
window). Otherwise grace expiry at the window start is reported as
`INSUFFICIENT_VACANCY_CONTEXT` instead of being assumed.

## Checks (2026-09-24)

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **45 passed**. The 1 warning is Starlette's existing httpx→httpx2 notice. |
| `.venv\Scripts\python.exe -m pip check` | No broken requirements found |
| `.venv\Scripts\python.exe scripts\check_env.py` | Python 3.13.15 venv, imports OK |
| `node scripts/verify-contract.mjs` | 75 passed, 0 failed |

The new tests (`tests/test_analyze.py`, 37 cases) cover:

- **Reference fixture:** matches the `expected.json` oracle finding (type,
  room, device, window, method, observed 0.01 kWh, expected 0 kWh,
  avoidable 0.01 kWh), with ₹0.10 at ₹10/kWh. There are no probabilities
  and `method` is `rule`.
- **Refrigerator:** excluded (always-on exception).
- **Occupied room:** no finding.
- **Grace not elapsed** (vacant from minute 1, grace 120 s, 2 minutes): no
  finding and no context warning.
- **Grace 120 s:** counted only from 03:33 (0.02 kWh). With grace 90 s,
  expiry 03:32:30 inside an interval with the device on throughout gives
  0.015 kWh (constant power). A partly-on straddling interval gives
  `SUB_INTERVAL_TIMING` and no claim.
- **Insufficient preceding context:**
  - vacant from the first minute, grace 120 s: the finding starts only at
    03:32, with an `INSUFFICIENT_VACANCY_CONTEXT` warning;
  - grace 300 s over 2 minutes: no finding, plus the warning.
- **Zero grace, fully vacant interval:** a direct finding.
- **Mixed occupancy** (0.5): no finding and 2 `MIXED_OCCUPANCY` warnings.
- **Unknown standby:** observed in seconds, no energy estimate.
- **Override:** described in `assumptions`.
- **Future policy:** `effective_from_utc` after the interval start returns
  400 at `device_intervals[0].policy_ref`.
- **15 invalid-request cases:**
  - unknown room/device/policy;
  - device interval in the wrong room; unknown room in a room interval;
  - inconsistent energy; seconds mismatch; impossible date (Feb 30);
  - interval outside the window; max < avg; on_fraction 1.5;
  - negative grace; bad `applies_to`; missing window; unknown field.
  All give 400 `VALIDATION_ERROR` with the exact field.
- **Version and JSON:** version 1.0.0 gives `UNSUPPORTED_VERSION`; malformed
  JSON gives 400.
- **Duplicates:** an identical duplicate is deduplicated with a warning;
  a conflicting duplicate gives 400.
- **Bounds:** 2,001 device or room intervals give 413 with the exact
  message; exactly 2,000 is accepted.
- **Forbidden fields:** at 5 positions (device interval, room interval,
  nested policy rules, options, top level) each gives 400 naming the path.
- **Model truthfulness:** health still reports `model_available: false`;
  model-info versions are null; analyze succeeds without `MODEL_UNAVAILABLE`;
  forecast returns 404.

The fixture's `expected.json` is read **only** as an evaluation oracle in
tests. It is never an input.

## Live HTTP evidence (port 8000)

- **Start command:** `.venv\Scripts\python.exe -m app`, with launcher PID
  15684 and interpreter PID 21608, bound to 127.0.0.1:8000.
- **Request:** the documented valid request built from the contract fixture
  (synthetic, not a production dataset).

- `GET http://localhost:8000/health` → 200
  `{"data":{"status":"ok","model_available":false},"meta":{"request_id":"0e56d0c7-550f-46f5-b9f9-d6fdccbf58e0"}}`
- `GET http://localhost:8000/v1/model/info` → 200
  `{"data":{"model_available":false,"model_version":null,"baseline_version":null,"contract_version":"1.0.1"},"meta":{"request_id":"d6147640-8d02-44b4-88c6-b286f7935b90"}}`
- `POST /v1/analyze` with the same request plus
  `device_intervals[1].fault_active` → 400
  `{"error":{"code":"VALIDATION_ERROR","message":"Injected-fault field 'fault_active' is forbidden in analysis inputs","field":"device_intervals[1].fault_active"}}`
- `POST /v1/analyze` with 2,001 device intervals → 413
  `{"error":{"code":"REQUEST_TOO_LARGE","message":"device_intervals has 2001 records; the bound is 2000. Narrow the window and preserve temporal context.","field":"device_intervals"}}`
- `POST /v1/forecast` → 404 `NOT_FOUND`.

Both PIDs were then stopped (`Stop-Process`, my own processes only) and port
8000 was free. **No process is left running.**

### Complete request — `POST http://localhost:8000/v1/analyze`

```json
{
  "contract_version": "1.0.1",
  "dataset_id": "ds-fixture",
  "run_id": "run-fixture-001",
  "window": {
    "start_utc": "2026-09-21T03:30:00Z",
    "end_utc": "2026-09-21T03:32:00Z"
  },
  "rooms": [
    {
      "capacity": 4,
      "floor_area_m2": 20,
      "name": "Room A",
      "room_id": "room-a",
      "room_type": "office"
    },
    {
      "capacity": 2,
      "floor_area_m2": 12,
      "name": "Room B",
      "room_id": "room-b",
      "room_type": "utility"
    }
  ],
  "devices": [
    {
      "always_on": false,
      "control": "scheduled",
      "controls": [
        "switch"
      ],
      "device_id": "light-a",
      "device_type": "lighting",
      "name": "Room A light",
      "nominal_power_w": 600,
      "power_factor": 1,
      "quantity": 1,
      "room_id": "room-a",
      "standby_power_w": 0
    },
    {
      "always_on": true,
      "control": "always_on",
      "controls": [],
      "device_id": "fridge-b",
      "device_type": "refrigerator",
      "name": "Room B refrigerator",
      "nominal_power_w": 300,
      "power_factor": 1,
      "quantity": 1,
      "room_id": "room-b",
      "standby_power_w": 0
    }
  ],
  "policies": [
    {
      "applies_to": "building:fixture-office",
      "effective_from_utc": "2026-09-21T03:30:00Z",
      "kind": "office_hours",
      "policy_id": "pol-hours",
      "rules": {
        "close_local": "18:00",
        "open_local": "09:00",
        "overnight": false,
        "working_days_iso": [
          1,
          2,
          3,
          4,
          5
        ]
      },
      "version": 1
    },
    {
      "applies_to": "device:light-a",
      "effective_from_utc": "2026-09-21T03:30:00Z",
      "kind": "lighting_schedule",
      "policy_id": "pol-light-a",
      "rules": {
        "on_during_hours": true,
        "vacancy_grace_seconds": 0
      },
      "version": 1
    },
    {
      "applies_to": "device:fridge-b",
      "effective_from_utc": "2026-09-21T03:30:00Z",
      "kind": "always_on",
      "policy_id": "pol-fridge-b",
      "rules": {
        "always_on_exception": true
      },
      "version": 1
    }
  ],
  "room_intervals": [
    {
      "avg_rh_pct": 55,
      "avg_temp_c": 27.5,
      "interval_end_utc": "2026-09-21T03:31:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:30:00Z",
      "occupancy_avg": 1,
      "occupancy_max": 1,
      "occupied_fraction": 1,
      "partial": false,
      "room_id": "room-a",
      "run_id": "run-fixture-001"
    },
    {
      "avg_rh_pct": 55,
      "avg_temp_c": 27.6,
      "interval_end_utc": "2026-09-21T03:32:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:31:00Z",
      "occupancy_avg": 0,
      "occupancy_max": 0,
      "occupied_fraction": 0,
      "partial": false,
      "room_id": "room-a",
      "run_id": "run-fixture-001"
    },
    {
      "avg_rh_pct": 60,
      "avg_temp_c": 24.5,
      "interval_end_utc": "2026-09-21T03:31:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:30:00Z",
      "occupancy_avg": 0,
      "occupancy_max": 0,
      "occupied_fraction": 0,
      "partial": false,
      "room_id": "room-b",
      "run_id": "run-fixture-001"
    },
    {
      "avg_rh_pct": 60,
      "avg_temp_c": 24.5,
      "interval_end_utc": "2026-09-21T03:32:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:31:00Z",
      "occupancy_avg": 0,
      "occupancy_max": 0,
      "occupied_fraction": 0,
      "partial": false,
      "room_id": "room-b",
      "run_id": "run-fixture-001"
    }
  ],
  "device_intervals": [
    {
      "avg_current_a": 3,
      "avg_power_w": 600,
      "avg_voltage_v": 200,
      "cumulative_kwh": 0.01,
      "device_id": "light-a",
      "energy_kwh": 0.01,
      "interval_end_utc": "2026-09-21T03:31:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:30:00Z",
      "max_power_w": 600,
      "offschedule_on_seconds": 0,
      "on_fraction": 1,
      "override_seconds": 0,
      "partial": false,
      "policy_ref": "pol-light-a:1",
      "power_factor": 1,
      "room_id": "room-a",
      "run_id": "run-fixture-001",
      "vacant_on_seconds": 0
    },
    {
      "avg_current_a": 3,
      "avg_power_w": 600,
      "avg_voltage_v": 200,
      "cumulative_kwh": 0.02,
      "device_id": "light-a",
      "energy_kwh": 0.01,
      "interval_end_utc": "2026-09-21T03:32:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:31:00Z",
      "max_power_w": 600,
      "offschedule_on_seconds": 0,
      "on_fraction": 1,
      "override_seconds": 0,
      "partial": false,
      "policy_ref": "pol-light-a:1",
      "power_factor": 1,
      "room_id": "room-a",
      "run_id": "run-fixture-001",
      "vacant_on_seconds": 60
    },
    {
      "avg_current_a": 1.5,
      "avg_power_w": 300,
      "avg_voltage_v": 200,
      "cumulative_kwh": 0.005,
      "device_id": "fridge-b",
      "energy_kwh": 0.005,
      "interval_end_utc": "2026-09-21T03:31:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:30:00Z",
      "max_power_w": 300,
      "offschedule_on_seconds": 0,
      "on_fraction": 1,
      "override_seconds": 0,
      "partial": false,
      "policy_ref": "pol-fridge-b:1",
      "power_factor": 1,
      "room_id": "room-b",
      "run_id": "run-fixture-001",
      "vacant_on_seconds": 60
    },
    {
      "avg_current_a": 1.5,
      "avg_power_w": 300,
      "avg_voltage_v": 200,
      "cumulative_kwh": 0.01,
      "device_id": "fridge-b",
      "energy_kwh": 0.005,
      "interval_end_utc": "2026-09-21T03:32:00Z",
      "interval_seconds": 60,
      "interval_start_utc": "2026-09-21T03:31:00Z",
      "max_power_w": 300,
      "offschedule_on_seconds": 0,
      "on_fraction": 1,
      "override_seconds": 0,
      "partial": false,
      "policy_ref": "pol-fridge-b:1",
      "power_factor": 1,
      "room_id": "room-b",
      "run_id": "run-fixture-001",
      "vacant_on_seconds": 60
    }
  ],
  "options": {
    "tariff_inr_per_kwh": 10
  }
}
```

### Complete response — HTTP 200

```json
{
  "data": {
    "findings": [
      {
        "finding_id": "vacant_but_on:light-a:2026-09-21T03:31:00Z",
        "finding_type": "vacant_but_on",
        "room_id": "room-a",
        "device_id": "light-a",
        "window_start_utc": "2026-09-21T03:31:00Z",
        "window_end_utc": "2026-09-21T03:32:00Z",
        "observed": {
          "value": 0.01,
          "unit": "kWh"
        },
        "expected": {
          "value": 0,
          "unit": "kWh"
        },
        "method": "rule",
        "suggested_action": "Switch off Room A light (light-a) in Room A when the room is vacant, as soon as it becomes vacant (0-second grace); review its schedule or occupancy-based control.",
        "assumptions": "Vacancy is taken from room intervals with occupancy_max = 0; the vacancy start is the start of the earliest contiguous fully vacant interval (a conservative lower bound; vacant from 2026-09-21T03:31:00Z or earlier). Vacancy grace 0 s from the applied policy version(s) pol-light-a:1. Avoidable energy = observed energy minus the off-state draw (0 W standby) over the same time.",
        "resolution_limit": "60-second intervals; sub-interval occupancy and switching times are not visible.",
        "evidence": {
          "rule_version": "vacant-beyond-grace-v1",
          "policy_refs": [
            "pol-light-a:1"
          ],
          "vacant_on_seconds_beyond_grace": 60,
          "intervals": [
            {
              "interval_start_utc": "2026-09-21T03:31:00Z",
              "interval_end_utc": "2026-09-21T03:32:00Z",
              "counted_from_utc": "2026-09-21T03:31:00Z",
              "vacant_on_seconds": 60,
              "energy_kwh": 0.01,
              "policy_ref": "pol-light-a:1"
            }
          ]
        },
        "avoidable_energy_kwh": 0.01,
        "avoidable_cost_inr": 0.1
      }
    ],
    "warnings": [
      {
        "code": "ANALYSES_NOT_PERFORMED",
        "message": "Only the deterministic vacant-beyond-grace rule is implemented. No drift detection, spike detection, anomaly model or forecast was performed, and no trained model was used."
      }
    ],
    "analysis": {
      "contract_version": "1.0.1",
      "dataset_id": "ds-fixture",
      "run_id": "run-fixture-001",
      "window": {
        "start_utc": "2026-09-21T03:30:00Z",
        "end_utc": "2026-09-21T03:32:00Z"
      },
      "method": "rule",
      "rules": [
        "vacant-beyond-grace-v1"
      ],
      "model_used": false,
      "records": {
        "room_intervals": 4,
        "device_intervals": 4,
        "duplicates_deduped": 0,
        "bounds": {
          "room_intervals": 2000,
          "device_intervals": 2000
        }
      },
      "excluded_devices": [
        {
          "device_id": "fridge-b",
          "reason": "always-on exception: vacant operation is by design"
        }
      ]
    }
  },
  "meta": {
    "request_id": "e40247fc-906f-4baa-bb59-ddd6d9b32027"
  }
}
```

## Limitations

- The rule works at interval resolution. Sub-interval timing is unknown, so
  mixed or straddling cases produce warnings, not claims.
- Only one rule exists. There is no schedule-violation, drift, spike or
  forecast analysis.
- Avoidable energy needs a known standby draw.
- Requests are bounded at 2,000 + 2,000 records. The caller must supply
  preceding context for grace expiry at window starts.
- A policy version whose `effective_from_utc` is later than an interval that
  references it is rejected. Simulator exports affected by the open
  run-policy timing defect (see simulation-backend
  `docs/KISHORE_BACKEND_HANDOFF.md`) will be **rejected** until that defect
  is fixed.

## Next-task dependencies

- **Auditor-backend (Codex/Mohan):** build bounded windows with preceding
  context from its database and call `POST /v1/analyze` server-side (F4).
- **Later rules and forecasting:** a later assignment. Any model must be
  trained and validated first, and `model_available` must only become true
  when a model is actually loaded.
