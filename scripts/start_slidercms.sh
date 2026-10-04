#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python}"
CELERY_BIN="${CELERY_BIN:-$VENV_DIR/bin/celery}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
# The kiosk and readiness check use loopback independently of Django's bind address.
SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
SLIDE_PATH="${SLIDE_PATH:-/slidedisplay/}"
TARGET_URL="${TARGET_URL:-http://${SERVER_HOST}:${PORT}${SLIDE_PATH}}"
cd "$PROJECT_DIR"
DATA_DIR="$("$PYTHON_BIN" -c 'from sliderCMS.runtime import DATA_DIR; print(DATA_DIR)')"
LOG_DIR="${LOG_DIR:-$DATA_DIR/logs}"
DJANGO_LOG="${DJANGO_LOG:-$LOG_DIR/django.log}"
CELERY_LOG="${CELERY_LOG:-$LOG_DIR/celery.log}"
XINIT_LOG="${XINIT_LOG:-$LOG_DIR/xinit.log}"
REDIS_LOG="${REDIS_LOG:-$LOG_DIR/redis.log}"
DJANGO_PID_FILE="${DJANGO_PID_FILE:-$LOG_DIR/django.pid}"
CELERY_PID_FILE="${CELERY_PID_FILE:-$LOG_DIR/celery.pid}"
XINIT_PID_FILE="${XINIT_PID_FILE:-$LOG_DIR/xinit.pid}"
REDIS_PID_FILE="${REDIS_PID_FILE:-$LOG_DIR/redis.pid}"
CELERY_POOL="${CELERY_POOL:-solo}"
BACKEND_ONLY=0

usage() {
  cat <<'EOF'
Usage: ./scripts/start_slidercms.sh [options]

Starts the local sliderCMS runtime:
  - Redis (if needed and not already running)
  - Django development server
  - Celery worker with beat
  - X11/openbox/Chromium kiosk session

Options:
  --backend-only   Start Redis, Django, and Celery without launching the kiosk browser session.
  -h, --help       Show this help.

Environment:
  HOST             Django bind address (default: 0.0.0.0, all IPv4 interfaces).
  PORT             Django port (default: 8000).
  SERVER_HOST      Local browser/readiness hostname (default: 127.0.0.1).
EOF
}

log() {
  printf '[sliderCMS start] %s\n' "$*"
}

warn() {
  printf '[sliderCMS start] warning: %s\n' "$*" >&2
}

die() {
  printf '[sliderCMS start] error: %s\n' "$*" >&2
  exit 1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

write_pid() {
  printf '%s\n' "$2" >"$1"
}

read_pid() {
  [ -f "$1" ] || return 1
  tr -d '[:space:]' <"$1"
}

is_pid_running() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

wait_for_http() {
  local url="$1"
  local attempts="${2:-30}"
  local i

  for i in $(seq 1 "$attempts"); do
    if "$PYTHON_BIN" - <<PY
import sys
import urllib.error
import urllib.request

url = "${url}"
try:
    with urllib.request.urlopen(url, timeout=2) as response:
        raise SystemExit(0 if response.status < 500 else 1)
except (urllib.error.URLError, TimeoutError):
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 1
  done

  return 1
}

ensure_requirements() {
  [ -f "$PROJECT_DIR/manage.py" ] || die "manage.py was not found in $PROJECT_DIR"
  [ -x "$PYTHON_BIN" ] || die "Python executable not found at $PYTHON_BIN. Run ./install.sh first."
  [ -x "$CELERY_BIN" ] || die "Celery executable not found at $CELERY_BIN. Run ./install.sh first."
  mkdir -p "$LOG_DIR"
}

start_redis_if_needed() {
  if have redis-cli && redis-cli ping >/dev/null 2>&1; then
    log "Redis is already running."
    return
  fi

  if [ -f "$REDIS_PID_FILE" ]; then
    local existing_pid
    existing_pid="$(read_pid "$REDIS_PID_FILE" || true)"
    if is_pid_running "$existing_pid"; then
      log "Redis is already running under PID $existing_pid."
      return
    fi
    rm -f "$REDIS_PID_FILE"
  fi

  if ! have redis-server; then
    die "redis-server was not found. Re-run ./install.sh on Raspberry Pi OS Lite to install the required runtime."
  fi

  log "Starting local Redis broker"
  redis-server \
    --daemonize yes \
    --save "" \
    --appendonly no \
    --bind 127.0.0.1 \
    --port 6379 \
    --pidfile "$REDIS_PID_FILE" \
    --logfile "$REDIS_LOG"

  sleep 1
  if have redis-cli && ! redis-cli ping >/dev/null 2>&1; then
    die "Redis failed to start correctly. Check $REDIS_LOG"
  fi
}

start_django() {
  local pid

  if [ -f "$DJANGO_PID_FILE" ]; then
    pid="$(read_pid "$DJANGO_PID_FILE" || true)"
    if is_pid_running "$pid"; then
      log "Django is already running under PID $pid."
      return
    fi
    rm -f "$DJANGO_PID_FILE"
  fi

  if ! "$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import socket
import sys
try:
    with socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((sys.argv[1], int(sys.argv[2])))
except (OSError, ValueError) as error:
    print(f'Cannot bind Django port: {error}', file=sys.stderr)
    raise SystemExit(1)
PY
  then
    die "Port $PORT is already in use or unavailable. Stop the old manual runserver before starting this launcher."
  fi

  log "Starting Django on ${HOST}:${PORT}"
  nohup "$PYTHON_BIN" "$PROJECT_DIR/manage.py" runserver "${HOST}:${PORT}" --noreload >"$DJANGO_LOG" 2>&1 &
  pid=$!
  write_pid "$DJANGO_PID_FILE" "$pid"
  "$PYTHON_BIN" -c 'import json,sys; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({"pid":int(sys.argv[2]),"host":sys.argv[3],"port":sys.argv[4]}))' "$LOG_DIR/runtime.json" "$pid" "$HOST" "$PORT"

  if ! wait_for_http "$TARGET_URL" 45; then
    die "Django did not become ready. Check $DJANGO_LOG"
  fi
  is_pid_running "$pid" || die "The Django process exited. Another server may be using port $PORT. Check $DJANGO_LOG"
}

start_celery() {
  local pid

  if [ -f "$CELERY_PID_FILE" ]; then
    pid="$(read_pid "$CELERY_PID_FILE" || true)"
    if is_pid_running "$pid"; then
      log "Celery is already running under PID $pid."
      return
    fi
    rm -f "$CELERY_PID_FILE"
  fi

  log "Starting Celery worker + beat"
  nohup "$CELERY_BIN" -A sliderCMS worker -B --schedule="$DATA_DIR/celerybeat-schedule" --pool="$CELERY_POOL" --loglevel=INFO >"$CELERY_LOG" 2>&1 &
  pid=$!
  write_pid "$CELERY_PID_FILE" "$pid"
  sleep 2

  if ! is_pid_running "$pid"; then
    die "Celery exited immediately. Check $CELERY_LOG"
  fi
}

start_kiosk_session() {
  local pid

  if [ "$BACKEND_ONLY" -eq 1 ]; then
    log "Backend-only mode enabled. Skipping X11/Chromium kiosk session."
    return
  fi

  if pgrep -f "Xorg :0" >/dev/null 2>&1; then
    log "Xorg is already running on :0. Launching a browser session into the existing display."
    DISPLAY=:0 nohup "$PROJECT_DIR/scripts/kiosk_session.sh" >"$XINIT_LOG" 2>&1 &
    pid=$!
    write_pid "$XINIT_PID_FILE" "$pid"
    return
  fi

  if [ -n "${SSH_CONNECTION:-}" ]; then
    warn "SSH session detected and no local X display is running. Backend services started, but the kiosk session was skipped."
    warn "Run ./scripts/start_slidercms.sh locally on tty1 to launch Chromium on the attached display."
    return
  fi

  if ! have xinit; then
    die "xinit was not found. Re-run ./install.sh to install the kiosk stack."
  fi

  log "Starting X11/openbox/Chromium kiosk session on :0"
  nohup xinit "$PROJECT_DIR/scripts/kiosk_session.sh" -- :0 vt1 >"$XINIT_LOG" 2>&1 &
  pid=$!
  write_pid "$XINIT_PID_FILE" "$pid"
  sleep 3

  if ! is_pid_running "$pid"; then
    die "The kiosk session exited immediately. Check $XINIT_LOG"
  fi
}

start_extra_hook() {
  local hook="$PROJECT_DIR/scripts/extra_startup.sh"
  local pid_file="$LOG_DIR/extra_startup.pid"
  local pid
  [ -f "$hook" ] || return 0
  pid="$(read_pid "$pid_file" || true)"
  if is_pid_running "$pid"; then
    log "Extra startup hook is already running under PID $pid."
    return
  fi
  log "Starting optional site hook (log: $LOG_DIR/extra_startup.log)."
  nohup bash "$hook" </dev/null >"$LOG_DIR/extra_startup.log" 2>&1 &
  pid=$!
  write_pid "$pid_file" "$pid"
  sleep 1
  if ! is_pid_running "$pid"; then
    if wait "$pid"; then
      log "Extra startup hook completed."
    else
      warn "Extra startup hook failed; backend services remain running. Check $LOG_DIR/extra_startup.log (sudo may need authorization before launch)."
    fi
    rm -f "$pid_file"
  fi
}

main() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --backend-only)
        BACKEND_ONLY=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
  done

  ensure_requirements
  start_redis_if_needed
  start_django
  start_celery
  start_extra_hook
  start_kiosk_session

  cat <<EOF

sliderCMS runtime started.

Django listening address:
  ${HOST}:${PORT}

Local browser URL (not the listening address):
  $TARGET_URL

Logs:
  Django: $DJANGO_LOG
  Celery: $CELERY_LOG
  X11:    $XINIT_LOG
  Redis:  $REDIS_LOG

Stop everything with:
  ./scripts/stop_slidercms.sh
EOF
}

main "$@"
