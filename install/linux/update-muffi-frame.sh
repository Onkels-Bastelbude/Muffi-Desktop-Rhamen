#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/muffi-frame}"
SERVICE_NAME="${SERVICE_NAME:-muffi-frame}"
VENV_DIR="$INSTALL_DIR/.venv"
REQUIREMENTS="$INSTALL_DIR/runtime/requirements.txt"

RED='\033[0;31m'; GRN='\033[0;32m'; BLU='\033[1;34m'; NC='\033[0m'
log() { printf "${BLU}[+]${NC} %s\n" "$*"; }
ok()  { printf "${GRN}[✓]${NC} %s\n" "$*"; }
die() { printf "${RED}[✗] %s${NC}\n" "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] && die "Bitte als normaler User ausführen, nicht root."
command -v git >/dev/null 2>&1 || die "git fehlt"
command -v systemctl >/dev/null 2>&1 || die "systemctl fehlt"

[[ -d "$INSTALL_DIR/.git" ]] || die "Keine Muffi-Installation gefunden unter: $INSTALL_DIR"

log "Hole neueste Version von GitHub"
git -C "$INSTALL_DIR" fetch --all --prune -q
git -C "$INSTALL_DIR" reset --hard origin/main -q

log "Python-Umgebung aktualisieren"
if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
  python3 -m venv "$VENV_DIR" --upgrade-deps 2>/dev/null || python3 -m venv "$VENV_DIR"
fi

if [[ -f "$REQUIREMENTS" ]]; then
  "$VENV_DIR/bin/pip" install -q -r "$REQUIREMENTS"
else
  "$VENV_DIR/bin/pip" install -q --upgrade pillow
fi

log "Service neu starten"
systemctl --user daemon-reload
systemctl --user restart "${SERVICE_NAME}.service"
systemctl --user is-active "${SERVICE_NAME}.service" >/dev/null

ok "Update abgeschlossen"
echo "Status: systemctl --user status ${SERVICE_NAME}"
