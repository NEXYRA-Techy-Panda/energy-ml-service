"""SYNTHETIC request builder for /v1/drift tests and the offline diagnostic.
Never used by the request path; scenario labels are returned separately.

Hourly intervals on the Asia/Kolkata local-hour grid (HH:30Z). Devices reuse
the P022 synthetic office: light-a 72 W, ws-group 960 W group total
(quantity 8) with an hour-of-day load profile, ac-a temperature-dependent,
fridge-b 150 W. By default each device reports local hours 09–17.
"""

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from ..anomalies.synthetic import DEVICES, POLICIES, ROOMS

IST = ZoneInfo("Asia/Kolkata")
REF_START_LOCAL = datetime(2026, 1, 5, tzinfo=IST)  # Monday
HOURS = tuple(range(9, 18))
POLICY_REF = {"light-a": "pol-light-a:1", "ws-group": "pol-ws-group:1", "ac-a": "pol-ac-a:1", "fridge-b": "pol-fridge-b:1"}
POLICIES_WITH_V2 = POLICIES + [{"policy_id": "pol-light-a", "version": 2, "kind": "lighting_schedule",
                                "rules": {"on_during_hours": True, "vacancy_grace_seconds": 600}}]

PowerFn = Callable[[str, str, int, int], tuple[float, float] | None]  # (section, device, day, local_hour)
RoomFn = Callable[[str, str, int, int], tuple[float, float] | None]  # (section, room, day, local_hour) → (temp, occupancy)
HoursFn = Callable[[str, str, int], tuple[int, ...]]  # (section, device, day) → local hours reported
PolicyFn = Callable[[str, str, int], str]


def fmt(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ws_profile(hour: int) -> float:
    return 820.0 if hour < 13 else 1100.0  # workstation load differs by time of day


def ac_level(temp: float) -> float:
    return 1100.0 + 80.0 * (temp - 24.0)


def default_room(section: str, room_id: str, day: int, hour: int) -> tuple[float, float]:
    return (25.0 + 0.5 * math.sin(hour / 3.0), 5.0 if room_id == "room-a" else 0.0)


def base_power(dev: str, hour: int, temp: float) -> float:
    return {"light-a": 72.0, "ws-group": ws_profile(hour), "fridge-b": 150.0}.get(dev) or ac_level(temp)


def build_drift_request(ref_days: int, eval_days: int, power: PowerFn, room: RoomFn | None = None, hours: HoursFn | None = None,
                        policy: PolicyFn | None = None, gap_days: int = 0, devices: list[dict] | None = None,
                        policies: list[dict] | None = None) -> dict:
    devices = devices or DEVICES
    room = room or default_room
    hours = hours or (lambda s, d, day: HOURS)
    policy = policy or (lambda s, d, day: POLICY_REF[d])
    body = {"contract_version": "1.0.1", "dataset_id": "ds-synthetic-drift", "run_id": "run-synthetic-drift",
            "rooms": ROOMS, "devices": devices, "policies": policies or POLICIES_WITH_V2}
    for section, n, offset in (("reference", ref_days, 0), ("evaluation", eval_days, ref_days + gap_days)):
        start = REF_START_LOCAL + timedelta(days=offset)
        room_rows, dev_rows = [], []
        for day in range(n):
            all_hours = sorted({h for d in devices for h in hours(section, d["device_id"], day)})
            for h in all_hours:
                t = start + timedelta(days=day, hours=h)
                end = t + timedelta(hours=1)
                for r in ROOMS:
                    ctx = room(section, r["room_id"], day, h)
                    if ctx is None:
                        continue
                    temp, occ = ctx
                    room_rows.append({"room_id": r["room_id"], "interval_start_utc": fmt(t), "interval_end_utc": fmt(end),
                                      "interval_seconds": 3600, "occupancy_avg": occ, "occupancy_max": math.ceil(occ),
                                      "occupied_fraction": 1.0 if occ > 0 else 0.0, "avg_temp_c": round(temp, 3), "avg_rh_pct": 55.0})
            for d in devices:
                for h in hours(section, d["device_id"], day):
                    p = power(section, d["device_id"], day, h)
                    if p is None:
                        continue  # missing reading: no record, never zero
                    w, on = p
                    t = start + timedelta(days=day, hours=h)
                    dev_rows.append({"device_id": d["device_id"], "room_id": d["room_id"], "interval_start_utc": fmt(t),
                                     "interval_end_utc": fmt(t + timedelta(hours=1)), "interval_seconds": 3600, "avg_power_w": w,
                                     "max_power_w": w, "energy_kwh": w * 3600 / 3_600_000, "on_fraction": on,
                                     "vacant_on_seconds": 0, "offschedule_on_seconds": 0,
                                     "policy_ref": policy(section, d["device_id"], day)})
        body[section] = {"window": {"start_utc": fmt(start), "end_utc": fmt(start + timedelta(days=n))},
                         "room_intervals": room_rows, "device_intervals": dev_rows}
    return body


def scenario_power(scenarios: dict[str, dict], eval_days: int, rng: random.Random, room: RoomFn = default_room) -> PowerFn:
    """Power generator: scenario per device = {"kind": stable|gradual|small|spike|step|offset, ...params}."""
    def power(section: str, dev: str, day: int, hour: int):
        temp = room(section, "room-a" if dev != "fridge-b" else "room-b", day, hour)[0]
        w = base_power(dev, hour, temp) * (1 + rng.gauss(0, 0.015))
        sc = scenarios.get(dev, {"kind": "stable"})
        if section == "evaluation":
            k = sc["kind"]
            if k in ("gradual", "small"):
                w *= 1 + sc["total"] * day / max(1, eval_days - 1)
            elif k == "spike" and day == sc["day"]:
                w *= sc["factor"]
            elif k == "step" and day >= sc["day"]:
                w *= 1 + sc["size"]
            elif k == "offset":
                w *= 1 + sc["size"]
        return (round(w, 4), 1.0)
    return power


def labelled_case(seed: int, ref_days: int = 14, eval_days: int = 28) -> tuple[dict, dict[str, str]]:
    """Held-out SYNTHETIC case: each device gets a random scenario. Returns (request, labels) with
    labels[device_id] in {"gradual", "small", "stable", "spike", "step", "offset"} (kept outside the request)."""
    rng = random.Random(seed)
    kinds = ["gradual", "small", "stable", "spike", "step", "offset"]
    scenarios, labels = {}, {}
    for d in ("light-a", "ws-group", "ac-a", "fridge-b"):
        k = rng.choice(kinds)
        sc = {"kind": k}
        if k == "gradual":
            sc["total"] = rng.uniform(0.2, 0.35)
        elif k == "small":
            sc["total"] = rng.uniform(0.02, 0.05)
        elif k == "spike":
            sc.update(day=rng.randrange(0, eval_days), factor=rng.uniform(1.5, 2.0))
        elif k == "step":
            sc.update(day=rng.randrange(7, eval_days - 7), size=rng.uniform(0.2, 0.4))
        elif k == "offset":
            sc["size"] = rng.uniform(0.15, 0.3)
        scenarios[d], labels[d] = sc, k
    drop = {day for day in range(eval_days) if rng.random() < 0.2}  # 20 % of evaluation days missing entirely
    base = scenario_power(scenarios, eval_days, rng)

    def power(section, dev, day, hour):
        if section == "evaluation" and day in drop:
            return None
        return None if rng.random() < 0.03 else base(section, dev, day, hour)

    return build_drift_request(ref_days, eval_days, power), labels
