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
    # TODO(question): should a car's starting driver default to cars[X].drivers[0]? Until
    # answered, driver stays None until the first driver_change event.
    # TODO(question): should a lap while status is pit/paddock imply the car is back on track?
    # Until answered, only pit_out/paddock_out change status.
    cars = {c: {"laps": [], "driver": None, "status": "track", "status_since": None} for c in CARS}

    for e in log:
        t = e["type"]
        if t == "race_config":
            config_payload = e["payload"]
        elif t == "race_start":
            race["started_at"] = e["ts"]
        elif t == "race_end":
            race["ended_at"] = e["ts"]
        elif t == "lap":
            cars[e["car"]]["laps"].append(e["ts"])
        elif t == "driver_change":
            cars[e["car"]]["driver"] = e["payload"]["driver"]
        elif t in STATUS_AFTER:
            cars[e["car"]]["status"] = STATUS_AFTER[t]
            cars[e["car"]]["status_since"] = e["ts"]

    return {
        "race_id": next(iter(race_ids), None),
        "last_seq": max((e["seq"] for e in events), default=0),
        "config": effective_config(config_payload),
        "race": race,
        "cars": cars,
        "log": log,
    }
