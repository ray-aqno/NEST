import random
import statistics

import pytest

from server.engine.laps import analyze
from server.engine.state import reduce
from tests.racelog import Log, at

MIN = 60_000


def run(log, now_ms):
    return analyze(reduce(log.events), at(now_ms))


# --- three seeded races: expected values come from the generator, not from the engine ---

def seeded_race(seed):
    rng = random.Random(seed)
    log = Log()
    log.add("race_start", 0)
    truth = {}
    pending = []
    for car in "AB":
        durations = [rng.randint(300_000, 420_000) for _ in range(rng.randint(12, 20))]
        t = 0
        for d in durations:
            t += d
            pending.append(("lap", t, car))
        truth[car] = durations
    rng.shuffle(pending)  # arrival order must not matter
    for type, t, car in pending:
        log.add(type, t, car=car)
    return log, truth


SEEDS = [1, 2, 3]


@pytest.mark.parametrize("seed", SEEDS)
def test_seeded_lap_counts_and_times(seed):
    log, truth = seeded_race(seed)
    a = run(log, 4 * 60 * MIN)
    for car, durations in truth.items():
        got = a["cars"][car]
        assert got["laps"] == len(durations)
        assert got["lap_times_s"] == [d / 1000 for d in durations]
        assert got["last_lap_s"] == durations[-1] / 1000


@pytest.mark.parametrize("seed", SEEDS)
def test_seeded_medians(seed):
    log, truth = seeded_race(seed)
    a = run(log, 4 * 60 * MIN)
    for car, durations in truth.items():
        assert a["cars"][car]["median_lap_s"] == pytest.approx(statistics.median(durations) / 1000)


@pytest.mark.parametrize("seed", SEEDS)
def test_seeded_stall_threshold(seed):
    log, truth = seeded_race(seed)
    for car, durations in truth.items():
        last = sum(durations)
        threshold = 1.5 * statistics.median(durations[-5:])
        before = run(log, int(last + threshold) - 1000)["cars"][car]["alerts"]
        after = run(log, int(last + threshold) + 1000)["cars"][car]["alerts"]
        assert [x["kind"] for x in before] == []
        assert [(x["kind"], x["car"]) for x in after] == [("stall", car)]


@pytest.mark.parametrize("seed", SEEDS)
def test_seeded_time_left(seed):
    log, _ = seeded_race(seed)
    now = random.Random(seed).randint(0, 240 * MIN)
    a = run(log, now)
    assert a["elapsed_s"] == now / 1000
    assert a["time_left_s"] == 240 * 60 - now / 1000


# --- rules and edges ---

def test_first_lap_without_race_start_has_no_time():
    log = Log()
    log.add("lap", 5 * MIN, car="A")
    log.add("lap", 11 * MIN, car="A")
    car = run(log, 12 * MIN)["cars"]["A"]
    assert (car["laps"], car["lap_times_s"]) == (2, [360.0])


def test_no_laps_means_no_lap_stats():
    car = run(Log(), 0)["cars"]["A"]
    assert (car["laps"], car["last_lap_s"], car["median_lap_s"], car["alerts"]) == (0, None, None, [])


def test_no_stall_below_minimum_laps():
    log = Log()
    log.add("race_start", 0)
    log.add("lap", 5 * MIN, car="A")
    log.add("lap", 10 * MIN, car="A")
    assert run(log, 120 * MIN)["cars"]["A"]["alerts"] == []


def test_stall_rule_values_come_from_config():
    log = Log()
    log.add("race_config", 0, stall_factor=3.0)
    log.add("race_start", 0)
    for i in range(1, 6):
        log.add("lap", i * 5 * MIN, car="A")
    assert run(log, 25 * MIN + 10 * MIN)["cars"]["A"]["alerts"] == []  # 2x median < 3x


def test_other_car_is_unaffected_by_a_stall():
    log = Log()
    log.add("race_start", 0)
    for i in range(1, 4):
        log.add("lap", i * 5 * MIN, car="A")
    log.add("lap", 40 * MIN, car="B")
    a = run(log, 40 * MIN)
    assert [x["car"] for x in a["cars"]["A"]["alerts"]] == ["A"]
    assert a["cars"]["B"]["alerts"] == []


def test_stint_runs_from_race_start_then_driver_change():
    log = Log()
    log.add("race_start", 0)
    assert run(log, 30 * MIN)["cars"]["A"]["stint_min"] == 30
    log.add("driver_change", 50 * MIN, car="A", driver="Ben")
    car = run(log, 80 * MIN)["cars"]["A"]
    assert (car["driver"], car["stint_min"]) == ("Ben", 30)


def test_no_stint_before_start():
    assert run(Log(), 10 * MIN)["cars"]["A"]["stint_min"] is None


def test_time_left_before_start_is_full_duration():
    a = run(Log(), 10 * MIN)
    assert (a["elapsed_s"], a["time_left_s"]) == (None, 240 * 60)


def test_race_end_freezes_clock():
    log = Log()
    log.add("race_start", 0)
    log.add("race_end", 100 * MIN)
    a = run(log, 300 * MIN)
    assert (a["elapsed_s"], a["time_left_s"]) == (100 * 60, 140 * 60)
    assert a["cars"]["A"]["stint_min"] == 100


def test_time_left_never_negative():
    log = Log()
    log.add("race_start", 0)
    assert run(log, 250 * MIN)["time_left_s"] == 0


def test_time_left_follows_config_duration():
    log = Log()
    log.add("race_config", 0, duration_min=180)
    log.add("race_start", 0)
    assert run(log, 60 * MIN)["time_left_s"] == 120 * 60


def test_distance_race_has_no_time_left():
    log = Log()
    log.add("race_config", 0, format="distance", distance_laps=12)
    log.add("race_start", 0)
    assert run(log, 60 * MIN)["time_left_s"] is None


def test_status_and_driver_pass_through():
    log = Log()
    log.add("race_config", 0, cars={"A": {"drivers": ["Ana"]}, "B": {"drivers": []}})
    log.add("pit_in", 5 * MIN, car="A", reason="fuel")
    car = run(log, 6 * MIN)["cars"]["A"]
    assert (car["status"], car["driver"]) == ("pit", "Ana")
