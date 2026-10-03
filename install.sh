#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

INSTALL_SYSTEM_DEPS=1
INSTALL_REDIS_MODE="auto"
INSTALL_KIOSK_MODE="auto"
RUN_MIGRATIONS=1
CREATE_SUPERUSER=0
ENABLE_CONSOLE_AUTOLOGIN=0
CONFIG_ARGS=()

OS_NAME="$(uname -s)"
LINUX_ID=""
LINUX_ID_LIKE=""
IS_RASPBERRY_PI=0
INSTALL_REDIS=0
INSTALL_KIOSK_STACK=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Sets up sliderCMS on macOS or Debian/Ubuntu, with an extra Raspberry Pi OS Lite path
that installs a minimal kiosk stack when needed.

Options:
  --no-system-deps             Skip apt/brew system package installation.
  --with-redis                 Force Redis installation.
  --without-redis              Skip Redis installation even on Raspberry Pi OS.
  --with-kiosk-stack           Force install of the minimal kiosk/X11/Chromium stack.
  --without-kiosk-stack        Skip kiosk stack installation.
  --enable-console-autologin   On Raspberry Pi OS, configure console auto-login with raspi-config.
  --migrate                    Run migrations (now the default).
  --createsuperuser            Run Django createsuperuser at the end.
  --repository OWNER/REPO      Public GitHub repository used for updates.
  --branch NAME                GitHub update branch (default: main).
  --enable-updates             Enable admin-triggered updates on this installation.
  --python PATH                Python executable to use for the virtualenv.
  -h, --help                   Show this help.

Environment:
  VENV_DIR=/path               Virtualenv location. Default: ./.venv
  PYTHON_BIN=python3.11        Python executable. Same as --python.
EOF
}

log() {
  printf '\033[1;32m==>\033[0m %s\n' "$*"
}

warn() {
  printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2
}

die() {
  printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
  exit 1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

run_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif have sudo; then
    sudo "$@"
  else
    die "This step needs root privileges, but sudo is not installed. Re-run as root or use --no-system-deps."
  fi
}

detect_linux_details() {
  if [ "$OS_NAME" != "Linux" ]; then
    return
  fi

  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    LINUX_ID="${ID:-}"
    LINUX_ID_LIKE="${ID_LIKE:-}"
  fi

  if [ -r /proc/device-tree/model ]; then
    if tr -d '\0' </proc/device-tree/model 2>/dev/null | grep -qi "raspberry pi"; then
      IS_RASPBERRY_PI=1
    fi
  elif [ "$LINUX_ID" = "raspbian" ]; then
    IS_RASPBERRY_PI=1
  fi
}

apply_install_defaults() {
  detect_linux_details

  if [ "$OS_NAME" = "Linux" ] && [ "$IS_RASPBERRY_PI" -eq 1 ]; then
    if [ "$INSTALL_REDIS_MODE" = "auto" ]; then
      INSTALL_REDIS=1
    fi
    if [ "$INSTALL_KIOSK_MODE" = "auto" ]; then
      INSTALL_KIOSK_STACK=1
    fi
  fi

  if [ "$INSTALL_REDIS_MODE" = "force-on" ]; then
    INSTALL_REDIS=1
  elif [ "$INSTALL_REDIS_MODE" = "force-off" ]; then
    INSTALL_REDIS=0
  fi

  if [ "$INSTALL_KIOSK_MODE" = "force-on" ]; then
    INSTALL_KIOSK_STACK=1
  elif [ "$INSTALL_KIOSK_MODE" = "force-off" ]; then
    INSTALL_KIOSK_STACK=0
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repository|--branch)
      [ "$#" -ge 2 ] || die "$1 requires a value."
      CONFIG_ARGS+=("$1" "$2")
      shift 2
      ;;
    --enable-updates)
      CONFIG_ARGS+=("$1")
      shift
      ;;
    --no-system-deps)
      INSTALL_SYSTEM_DEPS=0
      shift
      ;;
    --with-redis)
      INSTALL_REDIS_MODE="force-on"
      shift
      ;;
    --without-redis)
      INSTALL_REDIS_MODE="force-off"
      shift
      ;;
    --with-kiosk-stack)
      INSTALL_KIOSK_MODE="force-on"
      shift
      ;;
    --without-kiosk-stack)
      INSTALL_KIOSK_MODE="force-off"
      shift
      ;;
    --enable-console-autologin)
      ENABLE_CONSOLE_AUTOLOGIN=1
      shift
      ;;
    --migrate)
      RUN_MIGRATIONS=1
      shift
      ;;
    --createsuperuser)
      CREATE_SUPERUSER=1
      shift
      ;;
    --python)
      [ "$#" -ge 2 ] || die "--python requires a path or executable name."
      PYTHON_BIN="$2"
      shift 2
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

cd "$PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/manage.py" ] || [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
  die "Run this script from the sliderCMS project folder, or keep it beside manage.py."
fi

apply_install_defaults

apt_package_exists() {
  apt-cache show "$1" >/dev/null 2>&1
}

pick_apt_package() {
  local candidate
  for candidate in "$@"; do
    if [ -n "$candidate" ] && apt_package_exists "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

install_mac_system_deps() {
  if ! have brew; then
    warn "Homebrew is not installed. Install libmagic and poppler manually, or install Homebrew and rerun."
    return
  fi

  local packages=(python@3.11 libmagic poppler ffmpeg git)
  if [ "$INSTALL_REDIS" -eq 1 ]; then
    packages+=(redis)
  fi

  log "Installing macOS system packages with Homebrew: ${packages[*]}"
  brew update
  brew install "${packages[@]}"
}

install_debian_system_deps() {
  local chromium_package
  local packages=(
    python3
    python3-venv
    python3-pip
    python3-dev
    build-essential
    libmagic1
    poppler-utils
    curl
    ca-certificates
    rsync
    git
    ffmpeg
    cec-utils
    v4l-utils
  )

  run_sudo apt-get update

  if [ "$INSTALL_REDIS" -eq 1 ]; then
    packages+=(redis-server)
  fi

  if [ "$INSTALL_KIOSK_STACK" -eq 1 ]; then
    chromium_package="$(pick_apt_package chromium chromium-browser || true)"
    [ -n "$chromium_package" ] || die "Could not find a Chromium package (tried chromium and chromium-browser)."

    packages+=(
      "$chromium_package"
      chromium-sandbox
      xserver-xorg
      xinit
      openbox
      x11-xserver-utils
      xauth
      dbus-x11
      unclutter
    )
  fi

  log "Installing Debian system packages: ${packages[*]}"
  run_sudo apt-get install -y "${packages[@]}"
}

install_system_deps() {
  if [ "$INSTALL_SYSTEM_DEPS" -eq 0 ]; then
    warn "Skipping system dependencies. Make sure Python, libmagic, poppler, and any kiosk packages are already installed."
    return
  fi

  case "$OS_NAME" in
    Darwin)
      install_mac_system_deps
      ;;
    Linux)
      if [[ "$LINUX_ID" == "debian" || "$LINUX_ID" == "ubuntu" || "$LINUX_ID" == "raspbian" || "$LINUX_ID_LIKE" == *debian* ]]; then
        install_debian_system_deps
      else
        warn "Unsupported Linux distribution for automatic system package installation. Install Python 3, libmagic, poppler, and any kiosk packages manually."
      fi
      ;;
    *)
      warn "Unsupported OS '$OS_NAME' for automatic system package installation. Install Python 3, libmagic, and poppler manually."
      ;;
  esac
}

python_is_supported() {
  "$1" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

pick_python() {
  local candidates=("$PYTHON_BIN" python3.13 python3.12 python3.11 python3.10 python3)
  local candidate

  for candidate in "${candidates[@]}"; do
    if have "$candidate" && python_is_supported "$candidate"; then
      PYTHON_BIN="$candidate"
      return
    fi
  done

  die "Python 3.10 or newer is required for Django 5.2. Install Python 3.10+ or rerun with --python /path/to/python."
}

create_virtualenv() {
  pick_python

  log "Using Python: $("$PYTHON_BIN" --version 2>&1)"

  if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtualenv at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  else
    log "Reusing virtualenv at $VENV_DIR"
  fi

  # shellcheck source=/dev/null
  . "$VENV_DIR/bin/activate"

  log "Upgrading pip tooling"
  python -m pip install --upgrade pip setuptools wheel

  log "Installing Python dependencies"
  python -m pip install -r "$PROJECT_DIR/requirements.txt"
}

mark_runtime_scripts_executable() {
  chmod +x \
    "$PROJECT_DIR/install.sh" \
    "$PROJECT_DIR/launch_kiosk.sh" \
    "$PROJECT_DIR"/scripts/*.sh \
    "$PROJECT_DIR"/scripts/cec_*.py
}

configure_console_autologin() {
  if [ "$ENABLE_CONSOLE_AUTOLOGIN" -ne 1 ]; then
    return
  fi

  if [ "$OS_NAME" != "Linux" ] || [ "$IS_RASPBERRY_PI" -ne 1 ]; then
    warn "--enable-console-autologin is only applied on Raspberry Pi OS."
    return
  fi

  if ! have raspi-config; then
    warn "raspi-config is not installed, so console auto-login could not be configured automatically."
    return
  fi

  log "Configuring Raspberry Pi console auto-login with raspi-config"
  run_sudo raspi-config nonint do_boot_behaviour B2
}

django_checks() {
  # shellcheck source=/dev/null
  . "$VENV_DIR/bin/activate"

  log "Running Django system check"
  python manage.py check

  log "Setting up database and first administrator"
  python manage.py setup_site

  if [ "$CREATE_SUPERUSER" -eq 1 ]; then
    log "Creating Django superuser"
    python manage.py createsuperuser
  fi
}

print_summary() {
  cat <<EOF

Install complete.

Activate the environment:
  source "$VENV_DIR/bin/activate"

Run the development server:
  cd "$PROJECT_DIR"
  python manage.py runserver 0.0.0.0:8000

Kiosk helpers:
  Start: ./scripts/start_slidercms.sh
  Stop:  ./scripts/stop_slidercms.sh

Legacy wrapper:
  ./launch_kiosk.sh
EOF

  if [ "$OS_NAME" = "Linux" ] && [ "$INSTALL_KIOSK_STACK" -eq 1 ]; then
    cat <<EOF

Minimal Raspberry Pi kiosk stack installed:
  - Xorg / xinit
  - openbox
  - Chromium
  - unclutter
  - cec-utils
EOF
  fi

  if [ "$OS_NAME" = "Linux" ] && [ "$IS_RASPBERRY_PI" -eq 1 ]; then
    cat <<EOF

Raspberry Pi note:
  For the cleanest kiosk launch on Raspberry Pi OS Lite, log in on the local console
  (tty1) and run:

    ./scripts/start_slidercms.sh
EOF
  fi
}

main() {
  install_system_deps
  create_virtualenv
  "$VENV_DIR/bin/python" scripts/configure_install.py ${CONFIG_ARGS[@]+"${CONFIG_ARGS[@]}"}
  mark_runtime_scripts_executable
  configure_console_autologin
  django_checks
  print_summary
}

main
