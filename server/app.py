"""HTTP API (SPEC: API) and static UI. Run: uvicorn --factory server.app:create_app"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.engine.state import reduce
from server.events import EventIn
from server.store import Conflict, InvalidTarget, Store

ROOT = Path(__file__).resolve().parents[1]
STREAM_POLL_S = 0.25
STREAM_REFRESH_S = 1.0  # SPEC: state recomputes on each event and every 1 s


def utc_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def create_app(db_path: str | Path | None = None, ui_dir: str | Path | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("NEST_DB", ROOT / "data" / "nest.db")
    ui_dir = Path(ui_dir or os.environ.get("NEST_UI", ROOT / "ui" / "dist"))
    store = Store(db_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        store.close()

    app = FastAPI(title="NEST", lifespan=lifespan)

    def snapshot(race_id: str | None) -> dict[str, Any]:
        rid = race_id or store.latest_race_id()
        state = reduce(store.events(rid) if rid else [])
        return {**state, "now": utc_now()}

    @app.post("/events", status_code=201)
    def post_event(ev: EventIn, response: Response) -> dict[str, Any]:
        # A retry of an already-stored event answers 200 with the stored copy.
        # (Two simultaneous identical retries may both see 201; harmless.)
        if store.get(ev.id) is not None:
            response.status_code = 200
        try:
            return store.append(ev)
        except Conflict as e:
            raise HTTPException(409, str(e))
        except InvalidTarget as e:
            raise HTTPException(422, str(e))

    @app.get("/events")
    def get_events(race_id: str | None = None) -> list[dict[str, Any]]:
        rid = race_id or store.latest_race_id()
        return store.events(rid) if rid else []

    @app.get("/state")
    def get_state(race_id: str | None = None) -> dict[str, Any]:
        return snapshot(race_id)

    @app.get("/stream")
    async def stream(request: Request, race_id: str | None = None) -> StreamingResponse:
        async def events():
            sent_seq, sent_at = -1, 0.0
            while not await request.is_disconnected():
                seq = await asyncio.to_thread(store.last_seq)
                if seq != sent_seq or time.monotonic() - sent_at >= STREAM_REFRESH_S:
                    state = await asyncio.to_thread(snapshot, race_id)
                    yield f"data: {json.dumps(state)}\n\n"
                    sent_seq, sent_at = seq, time.monotonic()
                await asyncio.sleep(STREAM_POLL_S)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    if ui_dir.is_dir():
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")
    else:
        @app.get("/", response_class=PlainTextResponse)
        def no_ui() -> str:
            return f"NEST API is running, but the UI is not built ({ui_dir} missing). Run ./run.sh."

    return app
