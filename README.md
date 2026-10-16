# NEST

Pit-wall app for a two-car Baja SAE endurance team (car A = E3, car B = E4): lap logging, pit/paddock
tracking, stall alerts, race clock, and CVT sensor log analysis. Offline, one laptop, no cloud.

## Run

```
./run.sh
```

The first run sets up a Python 3.12 venv and builds the UI, so it needs network; do it before leaving
for the track. Later runs are fully offline. It serves on http://127.0.0.1:8000 and opens a browser.

## Develop

```
.venv/bin/pytest          # server tests
cd ui && npm run dev      # UI dev server (proxies the API on :8000)
```

Layout: `server/` (FastAPI app, SQLite store, pure engine in `server/engine/`), `ui/` (React + TS + Vite),
`tests/`, `docs/` (spec, discovery), `protocol/` (sensor line format).
