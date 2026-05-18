#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/muffi-frame}"
SERVICE_NAME="${SERVICE_NAME:-muffi-frame}"
UNIT_PATH="$HOME/.config/systemd/user/${SERVICE_NAME}.service"
PURGE=0

for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    *) echo "Unbekannte Option: $arg"; echo "Nutze optional: --purge"; exit 1 ;;
  esac
done

RED='\033[0;31m'; GRN='\033[0;32m'; BLU='\033[1;34m'; NC='\033[0m'
log() { printf "${BLU}[+]${NC} %s\n" "$*"; }
ok()  { printf "${GRN}[✓]${NC} %s\n" "$*"; }
die() { printf "${RED}[✗] %s${NC}\n" "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] && die "Bitte als normaler User ausführen, nicht root."
command -v systemctl >/dev/null 2>&1 || die "systemctl fehlt"

log "Stoppe und deaktiviere Service"
systemctl --user disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true

if [[ -f "$UNIT_PATH" ]]; then
  log "Entferne Unit-Datei"
  rm -f "$UNIT_PATH"
fi

systemctl --user daemon-reload

if [[ "$PURGE" -eq 1 ]]; then
  log "Lösche Installationsverzeichnis: $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  ok "Deinstallation inkl. Daten abgeschlossen"
else
  ok "Service deinstalliert. Daten bleiben erhalten unter: $INSTALL_DIR"
  echo "Tipp: Für vollständiges Entfernen -> bash install/linux/uninstall-muffi-frame.sh --purge"
fi
