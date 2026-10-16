import uuid

import pytest
from fastapi.testclient import TestClient

from server.app import create_app


def body(type="lap", car="A", race_id="baja", payload=None, id=None, ts="2026-10-17T15:00:00.000Z"):
    return {"id": id or str(uuid.uuid4()), "ts": ts, "race_id": race_id, "car": car,
            "type": type, "payload": payload or {}, "source": "manual"}


@pytest.fixture
def client(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>NEST</title>")
    with TestClient(create_app(db_path=tmp_path / "nest.db", ui_dir=ui)) as c:
        yield c


def test_post_event_returns_stored_event_with_seq(client):
    r = client.post("/events", json=body())
    assert r.status_code == 201
    assert r.json()["seq"] == 1


def test_retry_of_same_event_is_ok_not_duplicated(client):
    b = body()
    client.post("/events", json=b)
    r = client.post("/events", json=b)
    assert r.status_code == 200
    assert len(client.get("/events", params={"race_id": "baja"}).json()) == 1


def test_conflicting_id_is_409(client):
    b = body()
    client.post("/events", json=b)
    assert client.post("/events", json={**b, "car": "B"}).status_code == 409


def test_invalid_event_is_422(client):
    assert client.post("/events", json=body(type="lap", car=None)).status_code == 422


def test_void_of_unknown_target_is_422(client):
    r = client.post("/events", json=body(type="void", car=None, payload={"target_id": "nope"}))
    assert r.status_code == 422


def test_state_reflects_posted_laps(client):
    client.post("/events", json=body(car="B"))
    s = client.get("/state", params={"race_id": "baja"}).json()
    assert len(s["cars"]["B"]["laps"]) == 1
    assert s["now"].endswith("Z")


def test_state_defaults_to_latest_race(client):
    client.post("/events", json=body(race_id="practice"))
    client.post("/events", json=body(race_id="baja", car="B"))
    s = client.get("/state").json()
    assert s["race_id"] == "baja"


def test_state_with_no_events_is_empty_default(client):
    s = client.get("/state").json()
    assert s["race_id"] is None
    assert s["cars"]["A"]["laps"] == []


def test_ui_is_served_at_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>NEST</title>" in r.text


def test_state_includes_lap_analysis(client):
    client.post("/events", json=body(type="race_start", car=None, ts="2026-10-17T15:00:00.000Z"))
    client.post("/events", json=body(car="A", ts="2026-10-17T15:06:00.000Z"))
    a = client.get("/state").json()["analysis"]
    assert a["cars"]["A"]["last_lap_s"] == 360.0
    assert a["time_left_s"] is not None
