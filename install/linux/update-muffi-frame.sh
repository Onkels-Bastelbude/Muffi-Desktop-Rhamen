#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_INSTALL_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
REPO_URL="${REPO_URL:-https://github.com/Onkels-Bastelbude/Muffi-Desktop-Rhamen.git}"
SERVICE_NAME="${SERVICE_NAME:-muffi-frame}"
VENV_DIR="$INSTALL_DIR/.venv"
REQUIREMENTS="$INSTALL_DIR/runtime/requirements.txt"
SKIP_SERVICE_RESTART="${SKIP_SERVICE_RESTART:-0}"

RED='\033[0;31m'; GRN='\033[0;32m'; BLU='\033[1;34m'; NC='\033[0m'
log() { printf "${BLU}[+]${NC} %s\n" "$*"; }
ok()  { printf "${GRN}[✓]${NC} %s\n" "$*"; }
die() { printf "${RED}[✗] %s${NC}\n" "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] && die "Bitte als normaler User ausführen, nicht root."
command -v git >/dev/null 2>&1 || die "git fehlt"
command -v systemctl >/dev/null 2>&1 || die "systemctl fehlt"

if [[ ! -d "$INSTALL_DIR" ]]; then
  log "Installationsordner fehlt, klone Repo neu"
  git clone --depth=1 "$REPO_URL" "$INSTALL_DIR" -q
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  log "Kein Git-Repo gefunden -> Bootstrap initialisieren"
  git -C "$INSTALL_DIR" init -q
  if git -C "$INSTALL_DIR" remote get-url origin >/dev/null 2>&1; then
    git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
  else
    git -C "$INSTALL_DIR" remote add origin "$REPO_URL"
  fi
  git -C "$INSTALL_DIR" fetch --depth=1 origin main -q
  git -C "$INSTALL_DIR" reset --hard origin/main -q
fi

log "Hole neueste Version von GitHub"
git -C "$INSTALL_DIR" fetch --all --prune -q
git -C "$INSTALL_DIR" reset --hard origin/main -q

log "Python-Umgebung aktualisieren"
if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
  if ! python3 -m venv "$VENV_DIR" --upgrade-deps 2>/dev/null && ! python3 -m venv "$VENV_DIR"; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      log "python3-venv fehlt -> installiere automatisch"
      sudo apt-get update -qq
      sudo apt-get install -y python3-venv python3-pip >/dev/null 2>&1
      python3 -m venv "$VENV_DIR" --upgrade-deps 2>/dev/null || python3 -m venv "$VENV_DIR"
    else
      die "python3-venv fehlt. Bitte einmal manuell installieren: sudo apt-get install -y python3-venv python3-pip"
    fi
  fi
fi

if [[ -f "$REQUIREMENTS" ]]; then
  "$VENV_DIR/bin/pip" install -q -r "$REQUIREMENTS"
else
  "$VENV_DIR/bin/pip" install -q --upgrade pillow
fi

if [[ "$SKIP_SERVICE_RESTART" -eq 1 ]]; then
  log "Service-Restart übersprungen (SKIP_SERVICE_RESTART=1)"
else
  log "Service neu starten"
  systemctl --user daemon-reload
  systemctl --user restart "${SERVICE_NAME}.service"
  systemctl --user is-active "${SERVICE_NAME}.service" >/dev/null
fi

ok "Update abgeschlossen"
echo "Status: systemctl --user status ${SERVICE_NAME}"
