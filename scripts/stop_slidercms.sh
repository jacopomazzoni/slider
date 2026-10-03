#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"
DATA_DIR="$("$PYTHON_BIN" -c 'from sliderCMS.runtime import DATA_DIR; print(DATA_DIR)')"
LOG_DIR="${LOG_DIR:-$DATA_DIR/logs}"
DJANGO_PID_FILE="${DJANGO_PID_FILE:-$LOG_DIR/django.pid}"
CELERY_PID_FILE="${CELERY_PID_FILE:-$LOG_DIR/celery.pid}"
XINIT_PID_FILE="${XINIT_PID_FILE:-$LOG_DIR/xinit.pid}"
REDIS_PID_FILE="${REDIS_PID_FILE:-$LOG_DIR/redis.pid}"
QUIET=0

usage() {
  cat <<'EOF'
Usage: ./scripts/stop_slidercms.sh [options]

Stops the local sliderCMS runtime started by ./scripts/start_slidercms.sh.

Options:
  --quiet     Suppress informational output.
  -h, --help  Show this help.
EOF
}

log() {
  if [ "$QUIET" -eq 0 ]; then
    printf '[sliderCMS stop] %s\n' "$*"
  fi
}

read_pid() {
  [ -f "$1" ] || return 1
  tr -d '[:space:]' <"$1"
}

stop_pidfile() {
  local label="$1"
  local file="$2"
  local pid

  if [ ! -f "$file" ]; then
    return
  fi

  pid="$(read_pid "$file" || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    log "Stopping $label (PID $pid)"
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi

  rm -f "$file"
}

main() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --quiet)
        QUIET=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf '[sliderCMS stop] error: Unknown option: %s\n' "$1" >&2
        exit 1
        ;;
    esac
  done

  stop_pidfile "Chromium/X11 session" "$XINIT_PID_FILE"
  pkill -f "$PROJECT_DIR/scripts/kiosk_session.sh" 2>/dev/null || true
  pkill -x chromium 2>/dev/null || true
  pkill -x chromium-browser 2>/dev/null || true
  pkill -x google-chrome 2>/dev/null || true
  pkill -x openbox 2>/dev/null || true
  pkill -f "Xorg :0" 2>/dev/null || true

  stop_pidfile "Celery" "$CELERY_PID_FILE"
  pkill -f "$PROJECT_DIR/.*/celery -A sliderCMS worker -B" 2>/dev/null || true

  stop_pidfile "Django" "$DJANGO_PID_FILE"
  pkill -f "$PROJECT_DIR/manage.py runserver" 2>/dev/null || true

  stop_pidfile "Redis" "$REDIS_PID_FILE"

  log "sliderCMS runtime stopped."
}

main "$@"
