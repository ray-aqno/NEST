import json
import random

import pytest

from server.engine.state import reduce


class Log:
    """Builds stored-shape events (with server seq) for the reducer."""

    def __init__(self, race_id="baja"):
        self.race_id = race_id
        self.events = []

    def add(self, type, t, car=None, **payload):
        seq = len(self.events) + 1
        e = {"id": f"e{seq}", "seq": seq, "ts": f"2026-10-17T15:{t // 60:02d}:{t % 60:02d}.000Z",
             "race_id": self.race_id, "car": car, "type": type, "payload": payload, "source": "manual"}
        self.events.append(e)
        return e


def ts(t):
    return f"2026-10-17T15:{t // 60:02d}:{t % 60:02d}.000Z"


def test_empty_log_gives_default_state():
    s = reduce([])
    assert s["race_id"] is None
    assert s["last_seq"] == 0
    assert s["config"]["format"] == "time"
    assert s["race"] == {"started_at": None, "ended_at": None}
    assert set(s["cars"]) == {"A", "B"}
    assert s["cars"]["A"] == {"laps": [], "driver": None, "driver_since": None,
                              "status": "track", "status_since": None}


def test_lap_is_recorded_for_its_car():
    log = Log()
    log.add("lap", 10, car="A")
    s = reduce(log.events)
    assert s["cars"]["A"]["laps"] == [ts(10)]
    assert s["cars"]["B"]["laps"] == []


def test_void_removes_event_from_state():
    log = Log()
    lap = log.add("lap", 10, car="A")
    log.add("lap", 20, car="A")
    log.add("void", 25, target_id=lap["id"])
    s = reduce(log.events)
    assert s["cars"]["A"]["laps"] == [ts(20)]
    assert [e["type"] for e in s["log"]] == ["lap"]


def test_amend_moves_event_and_reorders():
    log = Log()
    log.add("lap", 10, car="A")
    late = log.add("lap", 20, car="A")
    log.add("amend", 30, target_id=late["id"], ts=ts(5))
    assert reduce(log.events)["cars"]["A"]["laps"] == [ts(5), ts(10)]


def test_latest_amend_wins():
    log = Log()
    lap = log.add("lap", 10, car="A")
    log.add("amend", 30, target_id=lap["id"], ts=ts(11))
    log.add("amend", 31, target_id=lap["id"], ts=ts(12))
    assert reduce(log.events)["cars"]["A"]["laps"] == [ts(12)]


def test_pit_and_paddock_status():
    log = Log()
    log.add("pit_in", 10, car="A", reason="fuel")
    assert reduce(log.events)["cars"]["A"]["status"] == "pit"
    log.add("pit_out", 40, car="A")
    s = reduce(log.events)
    assert (s["cars"]["A"]["status"], s["cars"]["A"]["status_since"]) == ("track", ts(40))
    log.add("paddock_in", 100, car="B", reason="cv axle")
    assert reduce(log.events)["cars"]["B"]["status"] == "paddock"
    log.add("paddock_out", 1300, car="B", reason="fixed")
    assert reduce(log.events)["cars"]["B"]["status"] == "track"


def test_driver_change_sets_driver():
    log = Log()
    log.add("driver_change", 10, car="B", driver="Sam")
    car = reduce(log.events)["cars"]["B"]
    assert (car["driver"], car["driver_since"]) == ("Sam", ts(10))


def test_driver_defaults_to_first_configured():
    log = Log()
    log.add("race_config", 0, cars={"A": {"drivers": ["Ana", "Ben"]}, "B": {"drivers": []}})
    s = reduce(log.events)
    assert (s["cars"]["A"]["driver"], s["cars"]["A"]["driver_since"]) == ("Ana", None)
    assert s["cars"]["B"]["driver"] is None


def test_lap_while_in_pit_returns_car_to_track():
    log = Log()
    log.add("pit_in", 10, car="A", reason="check")
    log.add("lap", 90, car="A")
    car = reduce(log.events)["cars"]["A"]
    assert (car["status"], car["status_since"], car["laps"]) == ("track", ts(90), [ts(90)])


def test_lap_on_track_does_not_touch_status_since():
    log = Log()
    log.add("pit_out", 10, car="A")
    log.add("lap", 90, car="A")
    assert reduce(log.events)["cars"]["A"]["status_since"] == ts(10)


def test_fuel_is_logged_but_not_modelled():
    log = Log()
    log.add("fuel_added", 10, car="A", liters=5.7, cans=1, filled_to_full=True)
    s = reduce(log.events)
    assert [e["type"] for e in s["log"]] == ["fuel_added"]
    assert set(s["cars"]["A"]) == {"laps", "driver", "driver_since", "status", "status_since"}


def test_latest_race_config_wins():
    log = Log()
    log.add("race_config", 1, format="time", duration_min=180)
    second = log.add("race_config", 2, format="distance", distance_laps=12)
    assert reduce(log.events)["config"]["format"] == "distance"
    log.add("void", 3, target_id=second["id"])
    s = reduce(log.events)
    assert (s["config"]["format"], s["config"]["duration_min"]) == ("time", 180)


def test_race_start_and_end():
    log = Log()
    log.add("race_start", 0)
    log.add("race_end", 600)
    assert reduce(log.events)["race"] == {"started_at": ts(0), "ended_at": ts(600)}


def test_last_seq_counts_corrections_too():
    log = Log()
    lap = log.add("lap", 10, car="A")
    log.add("void", 11, target_id=lap["id"])
    assert reduce(log.events)["last_seq"] == 2


def test_mixed_races_are_rejected():
    log = Log()
    log.add("lap", 10, car="A")
    other = Log(race_id="practice")
    other.add("lap", 10, car="A")
    with pytest.raises(ValueError):
        reduce(log.events + other.events)


def test_replay_is_deterministic():
    log = Log()
    log.add("race_config", 0, format="time", duration_min=240)
    log.add("race_start", 1)
    for i in range(40):
        log.add("lap", 60 + i * 7, car="AB"[i % 2])
    log.add("pit_in", 400, car="A", reason="driver")
    log.add("driver_change", 401, car="A", driver="Ana")
    log.add("pit_out", 450, car="A")
    log.add("void", 460, target_id="e5")
    log.add("amend", 461, target_id="e9", ts=ts(99))
    log.add("amend", 462, target_id="e9", ts=ts(100))  # latest amend must win
    log.add("note", 100, text="same ts as amended lap")  # tie broken by seq
    expected = json.dumps(reduce(log.events), sort_keys=True)
    rng = random.Random(7)
    for _ in range(20):
        shuffled = log.events[:]
        rng.shuffle(shuffled)
        assert json.dumps(reduce(shuffled), sort_keys=True) == expected


def test_reduce_does_not_mutate_input():
    log = Log()
    lap = log.add("lap", 10, car="A")
    log.add("amend", 11, target_id=lap["id"], ts=ts(9))
    before = json.dumps(log.events)
    reduce(log.events)
    assert json.dumps(log.events) == before
