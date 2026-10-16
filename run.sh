#!/usr/bin/env bash
# One-command start (NF-05): ./run.sh
# First run installs dependencies and needs network -- do it before leaving for the track.
# Every later run is fully offline (NF-01).
#   NEST_PORT=8000        port to serve on (127.0.0.1 only)
#   NEST_DB=data/nest.db  database file
#   NEST_NO_BROWSER=1     don't open a browser
set -euo pipefail
cd "$(dirname "$0")"

PORT="${NEST_PORT:-8000}"
URL="http://127.0.0.1:${PORT}"
PY=.venv/bin/python

if [ ! -f .venv/.nest-ready ]; then
  echo "First run: setting up Python 3.12 environment (needs network)..."
  rm -rf .venv
  if command -v uv >/dev/null 2>&1; then
    uv venv -q --python 3.12 .venv
    uv pip install -q --python "$PY" -r requirements.txt
  elif command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv .venv
    "$PY" -m pip install -q -r requirements.txt
  else
    echo "Need Python 3.12 or uv for first-time setup." >&2
    exit 1
  fi
  touch .venv/.nest-ready
fi

if [ ! -f ui/dist/index.html ]; then
  echo "First run: building UI (needs network)..."
  (cd ui && npm ci --no-audit --no-fund && npm run build)
fi

open_browser() {
  if command -v wslview >/dev/null 2>&1; then wslview "$URL"
  elif grep -qi microsoft /proc/version 2>/dev/null; then cmd.exe /c start "" "$URL" 2>/dev/null
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  elif command -v open >/dev/null 2>&1; then open "$URL"
  else echo "Open $URL in a browser."
  fi
}

if [ -z "${NEST_NO_BROWSER:-}" ]; then
  (
    for _ in $(seq 1 100); do
      if "$PY" -c "import urllib.request as u; u.urlopen('$URL/state', timeout=0.5)" 2>/dev/null; then
        open_browser >/dev/null 2>&1 || echo "Open $URL in a browser."
        exit 0
      fi
      sleep 0.2
    done
    echo "Server did not answer at $URL" >&2
  ) &
fi

echo "NEST on $URL  (Ctrl+C to stop)"
exec "$PY" -m uvicorn --factory server.app:create_app --host 127.0.0.1 --port "$PORT" --log-level warning
