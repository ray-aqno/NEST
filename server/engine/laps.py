"""Lap analysis (T4): pure function of reduced state (engine/state.py) and `now`. No I/O.

All arithmetic is in integer milliseconds so lap times are exact. Fuel is Phase 2 and not here.
"""

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ms(ts: str) -> int:
    return (datetime.fromisoformat(ts) - EPOCH) // timedelta(milliseconds=1)


def lap_times_ms(laps: list[int], start_ms: int | None) -> list[int]:
    """Lap time = gap to the car's previous lap, or to race_start for its first lap."""
    times, prev = [], start_ms
    for t in laps:
        if prev is not None and prev <= t:
            times.append(t - prev)
        prev = t
    return times


def _stall(car_id: str, laps: list[int], times: list[int], cfg: dict[str, Any], now_ms: int,
           last_lap_at: str) -> list[dict[str, Any]]:
    if len(laps) < cfg["stall_min_laps"] or not times:
        return []
    threshold = cfg["stall_factor"] * statistics.median(times[-cfg["stall_window_laps"]:])
    # TODO(question): suppress stall while the car is in pit/paddock, or after race_end?
    # SPEC states the rule without exceptions, so none are applied.
    since = now_ms - laps[-1]
    if since <= threshold:
        return []
    return [{"kind": "stall", "car": car_id, "last_lap_at": last_lap_at,
             "threshold_s": threshold / 1000, "overdue_s": (since - threshold) / 1000}]


def analyze(state: dict[str, Any], now: str) -> dict[str, Any]:
    cfg = state["config"]
    now_ms = _ms(now)
    start_ms = _ms(state["race"]["started_at"]) if state["race"]["started_at"] else None
    end = state["race"]["ended_at"]
    clock_ms = min(now_ms, _ms(end)) if end else now_ms  # race_end freezes the race clock

    elapsed_ms = max(0, clock_ms - start_ms) if start_ms is not None else None
    time_left_s = None
    if cfg["format"] == "time" and cfg["duration_min"] is not None:
        total_s = cfg["duration_min"] * 60
        time_left_s = total_s if elapsed_ms is None else max(0.0, total_s - elapsed_ms / 1000)

    cars = {}
    for car_id, car in state["cars"].items():
        laps = [_ms(t) for t in car["laps"]]
        times = lap_times_ms(laps, start_ms)

        # Stint = time since the last driver_change, or race_start (decided 2026-10-15).
        anchors = [m for m in (start_ms, _ms(car["driver_since"]) if car["driver_since"] else None)
                   if m is not None]
        stint_min = max(0, clock_ms - max(anchors)) / 60_000 if anchors else None

        cars[car_id] = {
            "laps": len(laps),
            "lap_times_s": [t / 1000 for t in times],
            "last_lap_s": times[-1] / 1000 if times else None,
            "median_lap_s": statistics.median(times) / 1000 if times else None,
            "stint_min": stint_min,
            "driver": car["driver"],
            "status": car["status"],
            "alerts": _stall(car_id, laps, times, cfg, now_ms, car["laps"][-1]) if laps else [],
        }

    return {
        "elapsed_s": elapsed_ms / 1000 if elapsed_ms is not None else None,
        "time_left_s": time_left_s,
        "cars": cars,
    }
