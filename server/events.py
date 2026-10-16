"""Event envelope, per-type payload schemas, and race config (SPEC: Event envelope, Config)."""

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULTS_PATH = Path(__file__).with_name("defaults.json")

Car = Literal["A", "B"]

# Car events are meaningless without a car; race-wide events must not carry one.
CAR_REQUIRED = {"lap", "pit_in", "pit_out", "fuel_added", "driver_change", "paddock_in", "paddock_out"}
CAR_FORBIDDEN = {"race_config", "race_start", "race_end"}
CORRECTIONS = {"void", "amend"}


def normalize_id(value: str) -> str:
    """Event ids and correction targets share one canonical spelling (lowercase, hyphenated)."""
    return str(uuid.UUID(value))


def require_finite(value: Any) -> None:
    """JSON has no Infinity/NaN; storing one would break every later /state read."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("numbers must be finite")
    if isinstance(value, dict):
        for v in value.values():
            require_finite(v)
    elif isinstance(value, list):
        for v in value:
            require_finite(v)


def normalize_ts(value: str) -> str:
    """ISO8601 with timezone -> UTC, millisecond precision, 'Z' suffix (sorts lexically)."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("ts must include a timezone")
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Empty(_Payload):
    pass


class PitIn(_Payload):
    reason: Literal["fuel", "driver", "check"]


class FuelAdded(_Payload):
    liters: float = Field(ge=0)
    cans: int = Field(ge=0)
    filled_to_full: bool


class DriverChange(_Payload):
    driver: str


class Paddock(_Payload):
    reason: str


class Incident(_Payload):
    kind: Literal["stopped", "rollover", "black_flag", "other"]
    note: str = ""


class Note(_Payload):
    text: str


class Void(_Payload):
    target_id: str

    @field_validator("target_id")
    @classmethod
    def _target(cls, v: str) -> str:
        return normalize_id(v)


class Amend(_Payload):
    target_id: str
    ts: str

    @field_validator("target_id")
    @classmethod
    def _target(cls, v: str) -> str:
        return normalize_id(v)

    @field_validator("ts")
    @classmethod
    def _ts(cls, v: str) -> str:
        return normalize_ts(v)


class CarConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str = ""
    number: str = ""
    drivers: list[str] = []

    @field_validator("number", mode="before")
    @classmethod
    def _number(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int) else v


class ChannelConfig(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    pulses_per_rev: float = Field(gt=0)


class RaceConfig(BaseModel):
    # extra="allow": Phase 2 keys (tank_l, burn_l_per_lap, ...) are accepted but unused.
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    format: Literal["time", "distance", "heats"]
    duration_min: float | None = Field(default=None, gt=0)
    distance_laps: int | None = Field(default=None, gt=0)
    cars: dict[Car, CarConfig]
    channels: dict[str, ChannelConfig] = {}
    cvt_ratio_band: tuple[float, float] | None = None
    cvt_min_secondary_rpm: float | None = None
    # Stall alert: >= stall_min_laps laps and now - last lap > stall_factor * median(last stall_window_laps).
    stall_factor: float = Field(gt=0)
    stall_window_laps: int = Field(ge=1)
    stall_min_laps: int = Field(ge=1)

    @field_validator("cars")
    @classmethod
    def _both_cars(cls, v: dict[str, CarConfig]) -> dict[str, CarConfig]:
        # race_config is a full config: a missing car would leave the board with nothing to show.
        if set(v) != {"A", "B"}:
            raise ValueError("cars must configure both A and B")
        return v

    @field_validator("cvt_ratio_band")
    @classmethod
    def _band(cls, v: tuple[float, float] | None) -> tuple[float, float] | None:
        if v is not None and v[0] >= v[1]:
            raise ValueError("cvt_ratio_band must be [min, max] with min < max")
        return v


def load_defaults() -> dict[str, Any]:
    return json.loads(DEFAULTS_PATH.read_text())


def effective_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults overlaid by a race_config payload (top-level keys replace)."""
    merged = {**load_defaults(), **(payload or {})}
    return RaceConfig.model_validate(merged).model_dump(mode="json")


PAYLOADS: dict[str, type[BaseModel]] = {
    "race_start": Empty,
    "race_end": Empty,
    "lap": Empty,
    "pit_out": Empty,
    "pit_in": PitIn,
    "fuel_added": FuelAdded,
    "driver_change": DriverChange,
    "paddock_in": Paddock,
    "paddock_out": Paddock,
    "incident": Incident,
    "note": Note,
    "void": Void,
    "amend": Amend,
}

EventType = Literal[
    "race_config", "race_start", "race_end", "lap", "pit_in", "pit_out", "fuel_added",
    "driver_change", "paddock_in", "paddock_out", "incident", "note", "void", "amend",
]


class EventIn(BaseModel):
    """An event as submitted by a client. `seq` is assigned by the store."""

    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    race_id: str = Field(min_length=1)
    car: Car | None = None
    type: EventType
    payload: dict[str, Any] = {}
    source: Literal["manual", "lan", "telemetry"]

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return normalize_id(v)

    @field_validator("ts")
    @classmethod
    def _ts(cls, v: str) -> str:
        return normalize_ts(v)

    @model_validator(mode="after")
    def _check(self) -> "EventIn":
        if self.type in CAR_REQUIRED and self.car is None:
            raise ValueError(f"{self.type} requires car")
        if self.type in CAR_FORBIDDEN and self.car is not None:
            raise ValueError(f"{self.type} must not name a car")
        if self.type == "race_config":
            effective_config(self.payload)  # validate against defaults; store as sent
        else:
            self.payload = PAYLOADS[self.type].model_validate(self.payload).model_dump(mode="json")
        require_finite(self.payload)  # also covers untyped Phase 2 config keys
        return self
