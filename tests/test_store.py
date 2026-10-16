import sqlite3
import uuid

import pytest

from server.events import EventIn
from server.store import Conflict, InvalidTarget, Store


def mk(type="lap", car="A", payload=None, race_id="baja", ts="2026-10-17T15:00:00.000Z", id=None):
    return EventIn.model_validate({
        "id": id or str(uuid.uuid4()),
        "ts": ts,
        "race_id": race_id,
        "car": car,
        "type": type,
        "payload": payload or {},
        "source": "manual",
    })


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "nest.db")
    yield s
    s.close()


def test_append_assigns_monotonic_seq(store):
    seqs = [store.append(mk())["seq"] for _ in range(3)]
    assert seqs == [1, 2, 3]


def test_append_same_event_twice_is_idempotent(store):
    e = mk()
    first = store.append(e)
    again = store.append(e)
    assert again == first
    assert len(store.events("baja")) == 1


def test_same_id_with_different_content_conflicts(store):
    e = mk()
    store.append(e)
    with pytest.raises(Conflict):
        store.append(mk(id=e.id, car="B"))


def test_events_survive_reopen(tmp_path):
    s = Store(tmp_path / "nest.db")
    s.append(mk())
    s.close()
    s2 = Store(tmp_path / "nest.db")
    assert [e["type"] for e in s2.events("baja")] == ["lap"]
    s2.close()


def test_events_are_scoped_to_race(store):
    store.append(mk(race_id="baja"))
    store.append(mk(race_id="practice"))
    assert len(store.events("baja")) == 1


def test_void_keeps_original_event(store):
    lap = store.append(mk())
    store.append(mk(type="void", car=None, payload={"target_id": lap["id"]}))
    types = [e["type"] for e in store.events("baja")]
    assert types == ["lap", "void"]


def test_void_of_unknown_target_is_rejected(store):
    with pytest.raises(InvalidTarget):
        store.append(mk(type="void", car=None, payload={"target_id": "nope"}))


def test_void_of_other_race_target_is_rejected(store):
    lap = store.append(mk(race_id="practice"))
    with pytest.raises(InvalidTarget):
        store.append(mk(type="void", car=None, payload={"target_id": lap["id"]}))


def test_void_of_a_correction_is_rejected(store):
    lap = store.append(mk())
    void = store.append(mk(type="void", car=None, payload={"target_id": lap["id"]}))
    with pytest.raises(InvalidTarget):
        store.append(mk(type="void", car=None, payload={"target_id": void["id"]}))


def test_double_void_is_rejected(store):
    lap = store.append(mk())
    store.append(mk(type="void", car=None, payload={"target_id": lap["id"]}))
    with pytest.raises(InvalidTarget):
        store.append(mk(type="void", car=None, payload={"target_id": lap["id"]}))


def test_database_refuses_edits_and_deletes(tmp_path):
    s = Store(tmp_path / "nest.db")
    s.append(mk())
    s.close()
    raw = sqlite3.connect(tmp_path / "nest.db")
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("UPDATE events SET car = 'B'")
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("DELETE FROM events")
    raw.close()


def test_durability_pragmas(store):
    assert store.pragma("journal_mode") == "wal"
    assert store.pragma("synchronous") == 2  # FULL: fsync on every commit


def test_latest_race_id(store):
    assert store.latest_race_id() is None
    store.append(mk(race_id="practice"))
    store.append(mk(race_id="baja"))
    assert store.latest_race_id() == "baja"


def test_samples_round_trip(store):
    rows = [
        {"ch": "cvt_primary", "board_ms": 1000, "count": 10, "period_us": 20000, "ts_race": 0.0},
        {"ch": "cvt_secondary", "board_ms": 1000, "count": 4, "period_us": 0, "ts_race": None},
    ]
    store.insert_samples("baja", rows)
    got = store.samples("baja")
    assert [(r["ch"], r["count"], r["period_us"]) for r in got] == [
        ("cvt_primary", 10, 20000),
        ("cvt_secondary", 4, 0),
    ]
    assert store.samples("practice") == []
