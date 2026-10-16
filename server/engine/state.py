"""State reducer (T3): pure fold of one race's stored events into current state. No I/O.

Effective log = events minus void/amend, minus voided targets, with amended ts applied,
ordered by (ts, seq). Ordering never depends on input list order, so replay is deterministic.
Derived numbers (lap times, medians, stint, stall, time left) belong to engine/laps.py (T4).
"""

from typing import Any

from server.events import CORRECTIONS, effective_config

CARS = ("A", "B")

STATUS_AFTER = {
    "pit_in": "pit",
    "pit_out": "track",
    "paddock_in": "paddock",
    "paddock_out": "track",
}


def effective_log(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_seq = sorted(events, key=lambda e: e["seq"])
    voided = {e["payload"]["target_id"] for e in by_seq if e["type"] == "void"}
    amended_ts = {e["payload"]["target_id"]: e["payload"]["ts"] for e in by_seq if e["type"] == "amend"}
    log = [
        {**e, "ts": amended_ts.get(e["id"], e["ts"])}
        for e in by_seq
        if e["type"] not in CORRECTIONS and e["id"] not in voided
    ]
    return sorted(log, key=lambda e: (e["ts"], e["seq"]))


def reduce(events: list[dict[str, Any]]) -> dict[str, Any]:
    race_ids = {e["race_id"] for e in events}
    if len(race_ids) > 1:
        raise ValueError(f"reduce() takes one race, got {sorted(race_ids)}")

    log = effective_log(events)
    config_payload = None
    race = {"started_at": None, "ended_at": None}
    # driver None here means "not changed yet"; the configured first driver is filled in below.
    cars = {c: {"laps": [], "driver": None, "driver_since": None, "status": "track", "status_since": None}
            for c in CARS}

    for e in log:
        t = e["type"]
        if t == "race_config":
            config_payload = e["payload"]
        elif t == "race_start":
            race["started_at"] = e["ts"]
        elif t == "race_end":
            race["ended_at"] = e["ts"]
        elif t == "lap":
            car = cars[e["car"]]
            car["laps"].append(e["ts"])
            if car["status"] != "track":  # decided: a lap tap implies a missed pit_out/paddock_out
                car["status"], car["status_since"] = "track", e["ts"]
        elif t == "driver_change":
            cars[e["car"]]["driver"] = e["payload"]["driver"]
            cars[e["car"]]["driver_since"] = e["ts"]
        elif t in STATUS_AFTER:
            cars[e["car"]]["status"] = STATUS_AFTER[t]
            cars[e["car"]]["status_since"] = e["ts"]

    config = effective_config(config_payload)
    for c, car in cars.items():
        if car["driver"] is None:  # decided: before any driver_change, the first configured driver
            car["driver"] = next(iter(config["cars"][c]["drivers"]), None)

    return {
        "race_id": next(iter(race_ids), None),
        "last_seq": max((e["seq"] for e in events), default=0),
        "config": config,
        "race": race,
        "cars": cars,
        "log": log,
    }
