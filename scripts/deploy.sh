#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"

DEPLOY_SSH_USER=""
DEPLOY_SERVER_HOST=""
DEPLOY_REMOTE_ROOT="${DEPLOY_REMOTE_ROOT:-}"
DRY_RUN=0

usage() {
  cat <<EOF
Usage: ./scripts/deploy.sh [options]

Push this sliderCMS project to the remote server with rsync over SSH.

Behavior:
  - Reads DEPLOY_SSH_USER and DEPLOY_SERVER_HOST from $ENV_FILE
  - Prompts for them if missing, then stores them in $ENV_FILE
  - Prompts for the SSH password on every deploy through ssh/rsync
  - Syncs the current project folder to /home/<user>/$PROJECT_NAME on the server

Options:
  --dry-run              Show what would change without uploading anything.
  --remote-root PATH     Override the remote base directory. Default: /home/<user>
  --env-file PATH        Use a different .env file.
  -h, --help             Show this help.

Stored .env keys:
  DEPLOY_SSH_USER
  DEPLOY_SERVER_HOST

Optional override key:
  DEPLOY_REMOTE_ROOT
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

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

normalize_host() {
  local host
  host="$(trim "$1")"
  host="${host#ssh://}"
  host="${host#http://}"
  host="${host#https://}"
  host="${host%%/*}"
  printf '%s' "$host"
}

ensure_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    mkdir -p "$(dirname "$ENV_FILE")"
    cat >"$ENV_FILE" <<'EOF'
# sliderCMS runtime and deploy configuration
EOF
    chmod 600 "$ENV_FILE" 2>/dev/null || true
  fi
}

read_env_value() {
  local key="$1"
  local line value

  [ -f "$ENV_FILE" ] || return 0

  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$ENV_FILE" | tail -n 1 || true)"
  [ -n "$line" ] || return 0

  value="${line#*=}"
  value="$(trim "$value")"

  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value#\"}"
    value="${value%\"}"
  elif [[ "$value" == \'*\' ]]; then
    value="${value#\'}"
    value="${value%\'}"
  fi

  printf '%s' "$value"
}

upsert_env_value() {
  local key="$1"
  local value="$2"
  local temp_file

  ensure_env_file
  temp_file="$(mktemp)"

  awk -v key="$key" -v value="$value" '
    BEGIN { updated = 0 }
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "=" {
      print key "=" value
      updated = 1
      next
    }
    { print }
    END {
      if (!updated) {
        print key "=" value
      }
    }
  ' "$ENV_FILE" >"$temp_file"

  mv "$temp_file" "$ENV_FILE"
}

load_config() {
  DEPLOY_SSH_USER="${DEPLOY_SSH_USER:-$(read_env_value DEPLOY_SSH_USER)}"
  DEPLOY_SERVER_HOST="${DEPLOY_SERVER_HOST:-$(read_env_value DEPLOY_SERVER_HOST)}"

  if [ -z "$DEPLOY_REMOTE_ROOT" ]; then
    DEPLOY_REMOTE_ROOT="$(read_env_value DEPLOY_REMOTE_ROOT)"
  fi
}

prompt_for_config() {
  if [ -z "$DEPLOY_SERVER_HOST" ]; then
    read -r -p "Server host (for example pi-serv.rex-powan.ts.net): " DEPLOY_SERVER_HOST
  fi

  DEPLOY_SERVER_HOST="$(normalize_host "$DEPLOY_SERVER_HOST")"

  if [[ "$DEPLOY_SERVER_HOST" == *"@"* ]]; then
    if [ -z "$DEPLOY_SSH_USER" ]; then
      DEPLOY_SSH_USER="${DEPLOY_SERVER_HOST%@*}"
    fi
    DEPLOY_SERVER_HOST="${DEPLOY_SERVER_HOST#*@}"
  fi

  if [ -z "$DEPLOY_SSH_USER" ]; then
    read -r -p "SSH username: " DEPLOY_SSH_USER
  fi

  DEPLOY_SSH_USER="$(trim "$DEPLOY_SSH_USER")"
  DEPLOY_SERVER_HOST="$(trim "$DEPLOY_SERVER_HOST")"

  [ -n "$DEPLOY_SSH_USER" ] || die "SSH username cannot be empty."
  [ -n "$DEPLOY_SERVER_HOST" ] || die "Server host cannot be empty."

  upsert_env_value DEPLOY_SSH_USER "$DEPLOY_SSH_USER"
  upsert_env_value DEPLOY_SERVER_HOST "$DEPLOY_SERVER_HOST"

  if [ -n "$DEPLOY_REMOTE_ROOT" ]; then
    upsert_env_value DEPLOY_REMOTE_ROOT "$DEPLOY_REMOTE_ROOT"
  fi
}

require_tools() {
  have rsync || die "rsync is required but was not found."
  have ssh || die "ssh is required but was not found."
}

run_deploy() {
  local remote_root remote_project_dir ssh_command
  local -a rsync_args

  remote_root="${DEPLOY_REMOTE_ROOT:-/home/$DEPLOY_SSH_USER}"
  remote_root="${remote_root%/}"
  remote_project_dir="$remote_root/$PROJECT_NAME"

  ssh_command="ssh -o PreferredAuthentications=password,keyboard-interactive -o PubkeyAuthentication=no -o NumberOfPasswordPrompts=1 -o StrictHostKeyChecking=accept-new"

  rsync_args=(
    -avz
    --human-readable
    --progress
    --exclude ".git/"
    --exclude ".github/"
    --exclude ".venv/"
    --exclude ".venv311/"
    --exclude "__pycache__/"
    --exclude "*.pyc"
    --exclude "*.pyo"
    --exclude ".DS_Store"
    --exclude ".pytest_cache/"
    --exclude ".mypy_cache/"
    --exclude "db.sqlite3"
    --exclude "*.sqlite3-*"
    --exclude "data/"
    --exclude "backups/"
    --exclude "updates/"
    --exclude ".secret_key"
    --exclude "*.zip"
    --exclude "celerybeat-schedule*"
    --exclude "templates/dateline_announcements.json"
    --exclude "media/"
    --exclude "logs/"
    --exclude "emails/"
    --exclude ".env"
    --exclude ".env.*"
    --rsync-path="mkdir -p '$remote_project_dir' && rsync"
    -e "$ssh_command"
  )

  if [ "$DRY_RUN" -eq 1 ]; then
    rsync_args+=(--dry-run --itemize-changes)
  fi

  log "Deploying $PROJECT_NAME to ${DEPLOY_SSH_USER}@${DEPLOY_SERVER_HOST}:${remote_project_dir}/"
  log "SSH will ask for the password during the connection. Nothing is stored locally."

  rsync "${rsync_args[@]}" \
    "$PROJECT_DIR/" \
    "${DEPLOY_SSH_USER}@${DEPLOY_SERVER_HOST}:${remote_project_dir}/"

  cat <<EOF

Deploy complete.

Remote location:
  ${DEPLOY_SSH_USER}@${DEPLOY_SERVER_HOST}:${remote_project_dir}/

Next useful command:
  ssh ${DEPLOY_SSH_USER}@${DEPLOY_SERVER_HOST}
EOF
}

main() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --remote-root)
        [ "$#" -ge 2 ] || die "--remote-root requires a path."
        DEPLOY_REMOTE_ROOT="$2"
        shift 2
        ;;
      --env-file)
        [ "$#" -ge 2 ] || die "--env-file requires a path."
        ENV_FILE="$2"
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

  [ -f "$PROJECT_DIR/manage.py" ] || die "Run this script from the sliderCMS project folder, or keep it inside scripts/."

  require_tools
  load_config
  prompt_for_config
  run_deploy
}

main "$@"
