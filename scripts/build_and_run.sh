#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/manual-runserver.log"
BOOT_LOG="$LOG_DIR/manual-runserver-bootstrap.log"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8017}"
if [ -z "${PYTHON_BIN:-}" ]; then
  if [ -x "$PROJECT_DIR/.venv311/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv311/bin/python"
    ACTIVATE_SCRIPT_DEFAULT="$PROJECT_DIR/.venv311/bin/activate"
  else
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
    ACTIVATE_SCRIPT_DEFAULT="$PROJECT_DIR/.venv/bin/activate"
  fi
fi
ACTIVATE_SCRIPT="${ACTIVATE_SCRIPT:-${ACTIVATE_SCRIPT_DEFAULT:-$PROJECT_DIR/.venv/bin/activate}}"
URL="http://${HOST}:${PORT}/"

mkdir -p "$LOG_DIR"
: >"$BOOT_LOG"

printf 'Starting launcher at %s\n' "$(date)" >>"$BOOT_LOG"
printf 'Project: %s\n' "$PROJECT_DIR" >>"$BOOT_LOG"
printf 'Python bin: %s\n' "$PYTHON_BIN" >>"$BOOT_LOG"
printf 'Activate script: %s\n' "$ACTIVATE_SCRIPT" >>"$BOOT_LOG"

if command -v lsof >/dev/null 2>&1; then
  existing_pid="$(lsof -tiTCP:${PORT} -sTCP:LISTEN || true)"
  if [ -n "$existing_pid" ]; then
    kill "$existing_pid" 2>/dev/null || true
    sleep 1
  fi
fi

cd "$PROJECT_DIR"
if [ -f "$ACTIVATE_SCRIPT" ]; then
  # shellcheck disable=SC1090
  . "$ACTIVATE_SCRIPT"
  printf 'Activated venv. python=%s\n' "$(command -v python || true)" >>"$BOOT_LOG"
  python --version >>"$BOOT_LOG" 2>&1 || true
  nohup python manage.py runserver "${HOST}:${PORT}" --noreload >"$LOG_FILE" 2>&1 &
else
  printf 'Activate script missing, using direct interpreter.\n' >>"$BOOT_LOG"
  nohup "$PYTHON_BIN" manage.py runserver "${HOST}:${PORT}" --noreload >"$LOG_FILE" 2>&1 &
fi
server_pid=$!
printf 'Launched PID: %s\n' "$server_pid" >>"$BOOT_LOG"

for _ in $(seq 1 20); do
  if curl -fsS "$URL" >/dev/null 2>&1; then
printf 'sliderCMS server is running at %s\n' "$URL"
    printf 'Web preview only: this launcher does not start Celery/Beat. Use scripts/start_slidercms.sh --backend-only for screen scheduling.\n'
    printf 'PID: %s\n' "$server_pid"
    printf 'Log: %s\n' "$LOG_FILE"
    printf 'Bootstrap log: %s\n' "$BOOT_LOG"
    exit 0
  fi
  sleep 1
done

printf 'Server did not become ready. Check %s\n' "$LOG_FILE" >&2
printf 'Bootstrap diagnostics: %s\n' "$BOOT_LOG" >&2
exit 1
