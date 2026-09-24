"""SYNTHETIC request builder for /v1/anomalies tests and offline detection
evaluation. Never used by the request path. Labels (which intervals carry an
injected excess) are returned SEPARATELY and never placed in the request.

Office: room-a (lighting "light-a" 72 W, workstation group "ws-group" 8 × 120 W
= 960 W reported as the group total, AC "ac-a") and room-b (refrigerator
"fridge-b" 150 W). 5-minute intervals, UTC grid.
"""

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Callable

INTERVAL_SECONDS = 300
T0 = datetime(2026, 3, 2, tzinfo=timezone.utc)

DEVICES = [
    {"device_id": "light-a", "name": "Room A light", "room_id": "room-a", "device_type": "lighting", "always_on": False,
     "quantity": 1, "nominal_power_w": 72, "standby_power_w": 0, "control": "scheduled"},
    {"device_id": "ws-group", "name": "Workstation group", "room_id": "room-a", "device_type": "workstation_group", "always_on": False,
     "quantity": 8, "nominal_power_w": 960, "standby_power_w": 0, "control": "scheduled"},
    {"device_id": "ac-a", "name": "Room A AC", "room_id": "room-a", "device_type": "ac", "always_on": False,
     "quantity": 1, "nominal_power_w": 1500, "standby_power_w": 0, "control": "scheduled"},
    {"device_id": "fridge-b", "name": "Room B refrigerator", "room_id": "room-b", "device_type": "refrigerator", "always_on": True,
     "quantity": 1, "nominal_power_w": 150, "standby_power_w": 0, "control": "always_on"},
]
ROOMS = [{"room_id": "room-a", "name": "Room A", "capacity": 12}, {"room_id": "room-b", "name": "Room B", "capacity": 4}]
POLICIES = [
    {"policy_id": "pol-hours", "version": 1, "kind": "office_hours",
     "rules": {"working_days_iso": [1, 2, 3, 4, 5], "open_local": "09:00", "close_local": "18:00", "overnight": False}},
    {"policy_id": "pol-light-a", "version": 1, "kind": "lighting_schedule", "rules": {"on_during_hours": True, "vacancy_grace_seconds": 300}},
    {"policy_id": "pol-ws-group", "version": 1, "kind": "device_schedule", "rules": {"office_hours_ref": "pol-hours:1"}},
    {"policy_id": "pol-ac-a", "version": 1, "kind": "device_schedule", "rules": {"office_hours_ref": "pol-hours:1"}},
    {"policy_id": "pol-fridge-b", "version": 1, "kind": "always_on", "rules": {"always_on_exception": True}},
]
POLICY_REF = {"light-a": "pol-light-a:1", "ws-group": "pol-ws-group:1", "ac-a": "pol-ac-a:1", "fridge-b": "pol-fridge-b:1"}

# (section, device_id, index) -> (avg_power_w, on_fraction) or None for a missing reading
PowerFn = Callable[[str, str, int], tuple[float, float] | None]
# (section, room_id, index) -> (avg_temp_c, occupancy_avg) or None for a missing room interval
RoomFn = Callable[[str, str, int], tuple[float, float] | None]


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def start_of(section: str, i: int, n_ref: int, gap: int = 0) -> datetime:
    base = T0 if section == "reference" else T0 + timedelta(seconds=(n_ref + gap) * INTERVAL_SECONDS)
    return base + timedelta(seconds=i * INTERVAL_SECONDS)


def build_request(n_ref: int, n_eval: int, power: PowerFn, room: RoomFn | None = None, gap: int = 0,
                  devices: list[dict] | None = None) -> dict:
    devices = devices or DEVICES
    room = room or (lambda section, room_id, i: (25.0, 2.0 if room_id == "room-a" else 0.0))
    body = {"contract_version": "1.0.1", "dataset_id": "ds-synthetic-anomaly", "run_id": "run-synthetic-anomaly",
            "rooms": ROOMS, "devices": devices, "policies": POLICIES}
    for section, n in (("reference", n_ref), ("evaluation", n_eval)):
        rooms_out, devs_out = [], []
        for i in range(n):
            t = start_of(section, i, n_ref, gap)
            end = t + timedelta(seconds=INTERVAL_SECONDS)
            for r in ROOMS:
                ctx = room(section, r["room_id"], i)
                if ctx is None:
                    continue
                temp, occ = ctx
                rooms_out.append({"room_id": r["room_id"], "interval_start_utc": fmt(t), "interval_end_utc": fmt(end),
                                  "interval_seconds": INTERVAL_SECONDS, "occupancy_avg": occ, "occupancy_max": math.ceil(occ),
                                  "occupied_fraction": 1.0 if occ > 0 else 0.0, "avg_temp_c": temp, "avg_rh_pct": 55.0})
            for d in devices:
                p = power(section, d["device_id"], i)
                if p is None:
                    continue  # missing reading: no record (never zero)
                w, on = p
                devs_out.append({"device_id": d["device_id"], "room_id": d["room_id"], "interval_start_utc": fmt(t),
                                 "interval_end_utc": fmt(end), "interval_seconds": INTERVAL_SECONDS, "avg_power_w": w,
                                 "max_power_w": w, "energy_kwh": w * INTERVAL_SECONDS / 3_600_000, "on_fraction": on,
                                 "vacant_on_seconds": 0, "offschedule_on_seconds": 0, "policy_ref": POLICY_REF[d["device_id"]]})
        first, last = start_of(section, 0, n_ref, gap), start_of(section, n, n_ref, gap)
        body[section] = {"window": {"start_utc": fmt(first), "end_utc": fmt(last)}, "room_intervals": rooms_out, "device_intervals": devs_out}
    return body


NOMINAL = {"light-a": 72.0, "ws-group": 960.0, "fridge-b": 150.0}


def ac_power(temp: float) -> float:
    """Synthetic AC demand rising with room temperature (comfort-dependent)."""
    return 1100.0 + 80.0 * (temp - 24.0)


def labelled_case(seed: int, n_ref: int = 300, n_eval: int = 300) -> tuple[dict, dict[tuple[str, str], str]]:
    """Held-out SYNTHETIC detection case. Reference: daily temperature cycle
    24–28 °C, lights/workstations on in a daytime block with mixed-duty edges,
    one reference spike outlier per device. Evaluation: same patterns plus a
    heat spell (up to 30 °C, AC demand rises legitimately), and injected excess
    blocks: two strong (+35 %) and one subtle (+6 %). Returns (request, labels) where
    labels maps (device_id, interval_start_utc) → "strong" | "subtle"."""
    rng = random.Random(seed)
    day = 288  # 5-minute intervals per day

    def temp_at(section: str, i: int) -> float:
        base = 26.0 + 2.0 * math.sin(2 * math.pi * (i % day) / day)
        if section == "evaluation" and 180 <= i < 230:
            base += 3.0  # heat spell: context outside most of the reference
        return round(base, 2)

    def occ_at(i: int) -> float:
        return 6.0 if 100 <= i % day < 210 else 0.0

    # Injections (labels): chosen reproducibly per seed on eligible (fully-on) devices/indices.
    injected: dict[tuple[str, int], float] = {}
    strong_devices = rng.sample(["light-a", "ws-group", "fridge-b", "ac-a"], 2)
    for dev in strong_devices:
        start = rng.randrange(105, 180) if dev in ("light-a", "ws-group", "ac-a") else rng.randrange(0, 280)
        for i in range(start, start + 12):
            injected[(dev, i)] = 1.35
    subtle = rng.choice([d for d in ("light-a", "ws-group", "fridge-b") if d not in strong_devices] or ["fridge-b"])
    s0 = rng.randrange(110, 190) if subtle != "fridge-b" else rng.randrange(0, 280)
    for i in range(s0, s0 + 12):
        injected.setdefault((subtle, i), 1.06)

    spikes = {d: rng.randrange(0, n_ref) for d in ("light-a", "ws-group", "fridge-b", "ac-a")}

    def power(section: str, dev: str, i: int) -> tuple[float, float] | None:
        if rng.random() < 0.02:
            return None  # missing reading
        k = i % day
        if dev in ("light-a", "ws-group", "ac-a"):
            if k < 100 or k >= 210:
                return (0.0, 0.0)
            if k in (100, 209):
                on = 0.5  # mixed-duty edge
            else:
                on = 1.0
            level = ac_power(temp_at(section, i)) if dev == "ac-a" else NOMINAL[dev]
        else:
            on, level = 1.0, NOMINAL[dev]
        w = level * (1 + rng.gauss(0, 0.01))
        if section == "reference" and spikes.get(dev) == i:
            w *= 5.0  # reference outlier (spike)
        if section == "evaluation" and on == 1.0:
            w *= injected.get((dev, i), 1.0)
        return (round(w * on, 6), on)

    body = build_request(n_ref, n_eval, power, room=lambda s, r, i: (temp_at(s, i), occ_at(i) if r == "room-a" else 0.0))
    labels = {(dev, fmt(start_of("evaluation", i, n_ref))): ("strong" if factor > 1.1 else "subtle") for (dev, i), factor in injected.items()}
    return body, labels
