"""Test helper: builds stored-shape events at millisecond offsets from a fixed race morning."""

from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 10, 17, 15, 0, 0, tzinfo=timezone.utc)


def at(ms: int) -> str:
    t = BASE + timedelta(milliseconds=ms)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class Log:
    def __init__(self, race_id="baja"):
        self.race_id = race_id
        self.events = []

    def add(self, type, ms, car=None, **payload):
        seq = len(self.events) + 1
        e = {"id": f"e{seq}", "seq": seq, "ts": at(ms), "race_id": self.race_id, "car": car,
             "type": type, "payload": payload, "source": "manual"}
        self.events.append(e)
        return e
