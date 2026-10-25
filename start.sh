#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

PID_FILE="$APP_DIR/.sam.pid"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/sam.log"

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid command
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command" == *"$APP_DIR/main.py"* ]]
}

stop_app() {
  if ! is_running; then
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..40}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "SAM did not stop cleanly; leaving it running to avoid force-closing its work."
    return 1
  fi
  rm -f "$PID_FILE"
}

ACTION="${1:-start}"
case "$ACTION" in
  stop)
    if stop_app; then echo "SAM stopped."; fi
    exit 0
    ;;
  restart)
    stop_app
    ;;
  start) ;;
  *) echo "Usage: ./start.sh [start|stop|restart]" >&2; exit 2 ;;
esac

if is_running; then
  echo "SAM is already running (PID $(cat "$PID_FILE"))."
  exit 0
fi

PYTHON="python3"
if [[ ! -d "$APP_DIR/.venv" ]]; then
  echo "Creating the Python environment…"
  "$PYTHON" -m venv "$APP_DIR/.venv"
fi
PYTHON="$APP_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$APP_DIR/.venv/Scripts/python.exe"; fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Could not find the environment's Python executable." >&2
  exit 1
fi

if ! "$PYTHON" -c 'import PyQt6, fastapi, uvicorn' >/dev/null 2>&1; then
  if [[ -f "$APP_DIR/requirements.txt" ]]; then
    echo "Installing or updating SAM dependencies…"
    "$PYTHON" -m pip install -r "$APP_DIR/requirements.txt"
  else
    echo "requirements.txt is missing; cannot install app dependencies." >&2
    exit 1
  fi
fi

mkdir -p "$LOG_DIR"
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"
nohup "$PYTHON" -u "$APP_DIR/main.py" >>"$LOG_FILE" 2>&1 </dev/null &
APP_PID=$!
printf '%s\n' "$APP_PID" > "$PID_FILE"
sleep 1
if kill -0 "$APP_PID" 2>/dev/null; then
  echo "SAM started (PID $APP_PID). Log: $LOG_FILE"
else
  rm -f "$PID_FILE"
  echo "SAM exited during startup. Check $LOG_FILE" >&2
  exit 1
fi
