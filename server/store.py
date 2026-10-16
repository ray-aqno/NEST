"""Append-only SQLite store: events (the log) and samples (sensor data, not in the log).

Durability (NF-02): WAL + synchronous=FULL, so every commit is fsynced before append() returns.
Corrections are new void/amend events; triggers make UPDATE/DELETE on events impossible.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from server.events import CORRECTIONS, EventIn

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    id      TEXT NOT NULL UNIQUE,
    ts      TEXT NOT NULL,
    race_id TEXT NOT NULL,
    car     TEXT,
    type    TEXT NOT NULL,
    payload TEXT NOT NULL,
    source  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_race ON events (race_id, seq);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE IF NOT EXISTS samples (
    race_id   TEXT NOT NULL,
    ch        TEXT NOT NULL,
    board_ms  INTEGER NOT NULL,
    count     INTEGER NOT NULL,
    period_us INTEGER NOT NULL,
    ts_race   REAL
);
CREATE INDEX IF NOT EXISTS samples_race ON samples (race_id, ch, board_ms);
"""

COLUMNS = "seq, id, ts, race_id, car, type, payload, source"


class Conflict(Exception):
    """Same event id re-sent with different content."""


class InvalidTarget(Exception):
    """void/amend points at something it may not correct."""


def _row(r: tuple) -> dict[str, Any]:
    seq, id, ts, race_id, car, type, payload, source = r
    return {"id": id, "seq": seq, "ts": ts, "race_id": race_id, "car": car,
            "type": type, "payload": json.loads(payload), "source": source}


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def pragma(self, name: str) -> Any:
        return self._conn.execute(f"PRAGMA {name}").fetchone()[0]

    def append(self, ev: EventIn) -> dict[str, Any]:
        payload = json.dumps(ev.payload, sort_keys=True)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._get(ev.id)
                if existing is not None:
                    self._conn.execute("ROLLBACK")  # read-only so far; release the write lock
                    same = (existing["ts"], existing["race_id"], existing["car"], existing["type"],
                            existing["payload"], existing["source"]) == (
                            ev.ts, ev.race_id, ev.car, ev.type, ev.payload, ev.source)
                    if not same:
                        raise Conflict(f"event {ev.id} already stored with different content")
                    return existing
                if ev.type in CORRECTIONS:
                    self._check_target(ev)
                cur = self._conn.execute(
                    "INSERT INTO events (id, ts, race_id, car, type, payload, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ev.id, ev.ts, ev.race_id, ev.car, ev.type, payload, ev.source),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                # Any failure (invalid target, constraint, I/O) must not leave the shared
                # connection inside a transaction, or every later write fails at BEGIN.
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            return {"id": ev.id, "seq": cur.lastrowid, "ts": ev.ts, "race_id": ev.race_id,
                    "car": ev.car, "type": ev.type, "payload": json.loads(payload), "source": ev.source}

    def _get(self, id: str) -> dict[str, Any] | None:
        r = self._conn.execute(f"SELECT {COLUMNS} FROM events WHERE id = ?", (id,)).fetchone()
        return _row(r) if r else None

    def _check_target(self, ev: EventIn) -> None:
        target = self._get(ev.payload["target_id"])
        if target is None or target["race_id"] != ev.race_id:
            raise InvalidTarget(f"no event {ev.payload['target_id']} in race {ev.race_id}")
        if target["type"] in CORRECTIONS:
            raise InvalidTarget("corrections cannot be corrected")
        if ev.type == "void":
            already = self._conn.execute(
                "SELECT 1 FROM events WHERE type = 'void' AND json_extract(payload, '$.target_id') = ?",
                (target["id"],),
            ).fetchone()
            if already:
                raise InvalidTarget(f"event {target['id']} is already voided")

    # Reads take the lock too: the connection is shared, and an unlocked read could see a row
    # between INSERT and COMMIT, i.e. before it is durable.
    def get(self, id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._get(id)

    def events(self, race_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {COLUMNS} FROM events WHERE race_id = ? ORDER BY seq", (race_id,)
            ).fetchall()
        return [_row(r) for r in rows]

    def last_seq(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]

    def latest_race_id(self) -> str | None:
        with self._lock:
            r = self._conn.execute("SELECT race_id FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def insert_samples(self, race_id: str, rows: list[dict[str, Any]]) -> None:
        """All rows or none, in one transaction (one fsync, not one per row)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.executemany(
                    "INSERT INTO samples (race_id, ch, board_ms, count, period_us, ts_race) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(race_id, r["ch"], r["board_ms"], r["count"], r["period_us"], r["ts_race"])
                     for r in rows],
                )
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def samples(self, race_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ch, board_ms, count, period_us, ts_race FROM samples WHERE race_id = ? ORDER BY rowid",
                (race_id,),
            ).fetchall()
        return [dict(zip(("ch", "board_ms", "count", "period_us", "ts_race"), r)) for r in rows]
