"""Against a real uvicorn process: kill -9 mid-race must lose nothing that was acknowledged
(NF-02) and a restart must restore identical state (NF-03). Also checks /stream (SSE)."""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, db: Path):
        self.db = db
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc = None

    def start(self):
        env = {**os.environ, "NEST_DB": str(self.db)}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "--factory", "server.app:create_app", "--port", str(self.port), "--log-level", "warning"],
            cwd=ROOT, env=env,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if httpx.get(self.url + "/state", timeout=0.5).status_code == 200:
                    return
            except httpx.TransportError:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def kill(self):
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path / "nest.db")
    s.start()
    yield s
    if s.proc.poll() is None:
        s.kill()


def lap(car, i):
    return {"id": str(uuid.uuid4()), "ts": f"2026-10-17T15:{i // 60 % 60:02d}:{i % 60:02d}.000Z",
            "race_id": "baja", "car": car, "type": "lap", "payload": {}, "source": "manual"}


def without_now(state):
    # `now` and `analysis` depend on the wall clock; analysis is covered by test_laps.py.
    return {k: v for k, v in state.items() if k not in ("now", "analysis")}


def test_kill_mid_race_loses_no_acknowledged_event(server):
    acked, stop = [], threading.Event()

    def tap():
        with httpx.Client(base_url=server.url, timeout=2) as c:
            i = 0
            while not stop.is_set():
                ev = lap("AB"[i % 2], i)
                try:
                    if c.post("/events", json=ev).status_code == 201:
                        acked.append(ev["id"])
                except httpx.TransportError:
                    return
                i += 1

    t = threading.Thread(target=tap)
    t.start()
    time.sleep(1.0)
    server.kill()  # while taps are in flight
    stop.set()
    t.join()
    assert len(acked) > 20

    server.start()
    stored = {e["id"] for e in httpx.get(server.url + "/events", params={"race_id": "baja"}).json()}
    assert set(acked) <= stored


def test_restart_restores_identical_state(server):
    with httpx.Client(base_url=server.url) as c:
        c.post("/events", json={**lap("A", 0), "type": "race_start", "car": None})
        for i in range(1, 30):
            c.post("/events", json=lap("AB"[i % 2], i * 3))
        before = without_now(c.get("/state").json())
    server.kill()
    server.start()
    after = without_now(httpx.get(server.url + "/state").json())
    assert after == before


def test_stream_sends_state_as_sse(server):
    httpx.post(server.url + "/events", json=lap("A", 5))
    with httpx.stream("GET", server.url + "/stream", timeout=5) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                state = json.loads(line[len("data: "):])
                break
    assert len(state["cars"]["A"]["laps"]) == 1
