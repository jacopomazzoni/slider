#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
SLIDE_PATH="${SLIDE_PATH:-/slidedisplay/}"
TARGET_URL="${TARGET_URL:-http://${SERVER_HOST}:${PORT}${SLIDE_PATH}}"
LOG_DIR="${LOG_DIR:-$PROJECT_DIR/logs}"
CHROMIUM_RAM_ROOT="${CHROMIUM_RAM_ROOT:-/dev/shm/slidercms-chromium}"
CHROMIUM_PROFILE_DIR="${CHROMIUM_PROFILE_DIR:-$CHROMIUM_RAM_ROOT/profile}"
CHROMIUM_CACHE_DIR="${CHROMIUM_CACHE_DIR:-$CHROMIUM_RAM_ROOT/cache}"
CHROMIUM_MEDIA_CACHE_DIR="${CHROMIUM_MEDIA_CACHE_DIR:-$CHROMIUM_RAM_ROOT/media-cache}"

log() {
  printf '[sliderCMS kiosk] %s\n' "$*"
}

warn() {
  printf '[sliderCMS kiosk] warning: %s\n' "$*" >&2
}

have() {
  command -v "$1" >/dev/null 2>&1
}

pick_chromium() {
  local candidate

  if [ -n "${CHROMIUM_BIN:-}" ]; then
    printf '%s\n' "$CHROMIUM_BIN"
    return
  fi

  for candidate in chromium chromium-browser google-chrome; do
    if have "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  return 1
}

mkdir -p "$LOG_DIR"

CHROMIUM_CMD="$(pick_chromium || true)"
[ -n "$CHROMIUM_CMD" ] || {
  warn "Chromium was not found. Install it with ./install.sh on Raspberry Pi OS Lite."
  exit 1
}

if ! have openbox-session && ! have openbox; then
  warn "openbox/openbox-session was not found."
  exit 1
fi

if [ ! -d /dev/shm ]; then
  CHROMIUM_RAM_ROOT="${CHROMIUM_RAM_ROOT:-/tmp/slidercms-chromium}"
  CHROMIUM_PROFILE_DIR="$CHROMIUM_RAM_ROOT/profile"
  CHROMIUM_CACHE_DIR="$CHROMIUM_RAM_ROOT/cache"
  CHROMIUM_MEDIA_CACHE_DIR="$CHROMIUM_RAM_ROOT/media-cache"
fi

mkdir -p "$CHROMIUM_PROFILE_DIR" "$CHROMIUM_CACHE_DIR" "$CHROMIUM_MEDIA_CACHE_DIR"

cleanup() {
  if [ -n "${UNCLUTTER_PID:-}" ] && kill -0 "$UNCLUTTER_PID" 2>/dev/null; then
    kill "$UNCLUTTER_PID" 2>/dev/null || true
  fi
  if [ -n "${OPENBOX_PID:-}" ] && kill -0 "$OPENBOX_PID" 2>/dev/null; then
    kill "$OPENBOX_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT

export NO_AT_BRIDGE=1
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$CHROMIUM_RAM_ROOT/xdg-cache}"
mkdir -p "$XDG_CACHE_HOME"

xset s off || true
xset -dpms || true
xset s noblank || true

if have unclutter; then
  unclutter -idle 1 -root >/dev/null 2>&1 &
  UNCLUTTER_PID=$!
fi

if have openbox-session; then
  openbox-session >/dev/null 2>&1 &
else
  openbox >/dev/null 2>&1 &
fi
OPENBOX_PID=$!

log "Launching $CHROMIUM_CMD against $TARGET_URL"
exec "$CHROMIUM_CMD" \
  --kiosk \
  --start-fullscreen \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-background-networking \
  --disable-component-update \
  --disable-features=Translate,InfiniteSessionRestore,MediaRouter \
  --autoplay-policy=no-user-gesture-required \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  --no-first-run \
  --disk-cache-dir="$CHROMIUM_CACHE_DIR" \
  --media-cache-dir="$CHROMIUM_MEDIA_CACHE_DIR" \
  --disk-cache-size=268435456 \
  --user-data-dir="$CHROMIUM_PROFILE_DIR" \
  --window-position=0,0 \
  "$TARGET_URL"
