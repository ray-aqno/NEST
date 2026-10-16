import pytest
from pydantic import ValidationError

from server.events import EventIn, effective_config


def ev(**kw):
    base = {
        "id": "00000000-0000-4000-8000-000000000001",
        "ts": "2026-10-17T15:00:00.000Z",
        "race_id": "baja",
        "car": "A",
        "type": "lap",
        "payload": {},
        "source": "manual",
    }
    base.update(kw)
    return EventIn.model_validate(base)


def test_lap_event_is_accepted():
    assert ev().type == "lap"


def test_unknown_type_is_rejected():
    with pytest.raises(ValidationError):
        ev(type="teleport")


def test_ts_is_normalised_to_utc_milliseconds():
    assert ev(ts="2026-10-17T10:00:00.5-05:00").ts == "2026-10-17T15:00:00.500Z"


def test_ts_without_timezone_is_rejected():
    with pytest.raises(ValidationError):
        ev(ts="2026-10-17T15:00:00")


def test_pit_in_requires_known_reason():
    assert ev(type="pit_in", payload={"reason": "fuel"}).payload == {"reason": "fuel"}
    with pytest.raises(ValidationError):
        ev(type="pit_in", payload={"reason": "nap"})


def test_fuel_added_payload_is_typed():
    e = ev(type="fuel_added", payload={"liters": 5.7, "cans": 1, "filled_to_full": True})
    assert e.payload["liters"] == 5.7
    with pytest.raises(ValidationError):
        ev(type="fuel_added", payload={"liters": "lots", "cans": 1, "filled_to_full": True})


def test_car_events_require_a_car():
    with pytest.raises(ValidationError):
        ev(type="lap", car=None)


def test_race_events_must_not_name_a_car():
    with pytest.raises(ValidationError):
        ev(type="race_start", car="A")
    assert ev(type="race_start", car=None).car is None


def test_void_and_amend_need_target():
    t = "00000000-0000-4000-8000-0000000000aa"
    assert ev(type="void", car=None, payload={"target_id": t}).payload == {"target_id": t}
    with pytest.raises(ValidationError):
        ev(type="void", car=None, payload={})
    with pytest.raises(ValidationError):
        ev(type="void", car=None, payload={"target_id": "not-a-uuid"})
    amend = ev(type="amend", car=None, payload={"target_id": t, "ts": "2026-10-17T10:00:01-05:00"})
    assert amend.payload["ts"] == "2026-10-17T15:00:01.000Z"


def test_unknown_source_is_rejected():
    with pytest.raises(ValidationError):
        ev(source="carrier_pigeon")


def test_race_config_is_validated():
    ok = ev(type="race_config", car=None, payload={"format": "distance", "distance_laps": 12})
    assert ok.payload["format"] == "distance"
    with pytest.raises(ValidationError):
        ev(type="race_config", car=None, payload={"format": "sprint"})


def test_race_config_accepts_phase2_keys():
    e = ev(type="race_config", car=None, payload={"tank_l": 20, "burn_l_per_lap": {"A": 1.1}})
    assert e.payload["tank_l"] == 20


def test_default_config_is_time_240():
    cfg = effective_config(None)
    assert cfg["format"] == "time"
    assert cfg["duration_min"] == 240
    assert cfg["cvt_ratio_band"] is None


def test_config_payload_overrides_defaults():
    cfg = effective_config({"duration_min": 180})
    assert cfg["format"] == "time"
    assert cfg["duration_min"] == 180


# --- review fixes (PR #1) ---

@pytest.mark.parametrize("cars", [{}, {"A": {"drivers": ["Ana"]}}])
def test_race_config_must_name_both_cars(cars):
    with pytest.raises(ValidationError):
        ev(type="race_config", car=None, payload={"cars": cars})


@pytest.mark.parametrize("payload", [
    {"duration_min": "inf"},
    {"cvt_ratio_band": [float("nan"), 3.0]},
    {"cvt_min_secondary_rpm": float("inf")},
    {"tank_l": float("inf")},  # Phase 2 key: untyped, still must be finite
])
def test_race_config_rejects_non_finite_numbers(payload):
    with pytest.raises(ValidationError):
        ev(type="race_config", car=None, payload=payload)


def test_payload_rejects_non_finite_numbers():
    with pytest.raises(ValidationError):
        ev(type="fuel_added", payload={"liters": "inf", "cans": 1, "filled_to_full": True})


def test_correction_target_is_normalised_like_event_ids():
    upper = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
    void = ev(type="void", car=None, payload={"target_id": upper})
    assert void.payload["target_id"] == upper.lower()
    amend = ev(type="amend", car=None, payload={"target_id": upper.replace("-", ""),
                                               "ts": "2026-10-17T15:00:01Z"})
    assert amend.payload["target_id"] == upper.lower()
