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
ESP32_INDEX_URL="${ESP32_INDEX_URL:-https://espressif.github.io/arduino-esp32/package_esp32_index.json}"

RED='\033[0;31m'; GRN='\033[0;32m'; BLU='\033[1;34m'; NC='\033[0m'
log() { printf "${BLU}[+]${NC} %s\n" "$*"; }
ok()  { printf "${GRN}[✓]${NC} %s\n" "$*"; }
die() { printf "${RED}[✗] %s${NC}\n" "$*" >&2; exit 1; }

git_version_label() {
  local rev="$1"
  local label=""
  if [[ -n "$rev" ]]; then
    label="$(git -C "$INSTALL_DIR" show -s --format='%cd' --date=format-local:'%Y%m%d-%H%M' "$rev" 2>/dev/null || true)"
  fi
  if [[ -z "$label" ]]; then
    label="unknown"
  fi
  printf "%s" "$label"
}

ensure_arduino_cli() {
  if command -v arduino-cli >/dev/null 2>&1; then
    ok "arduino-cli vorhanden ($(arduino-cli version | head -n1))"
    return
  fi

  if command -v curl >/dev/null 2>&1; then
    log "arduino-cli fehlt → installiere lokal unter ~/.local/bin …"
    mkdir -p "$HOME/.local/bin"
    curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh
    export PATH="$HOME/.local/bin:$PATH"
  fi

  command -v arduino-cli >/dev/null 2>&1 || die "arduino-cli fehlt. Bitte installieren (oder Installer erneut ausführen)."
  ok "arduino-cli bereit ($(arduino-cli version | head -n1))"
}

ensure_esp32_core() {
  if ! command -v arduino-cli >/dev/null 2>&1; then
    die "arduino-cli fehlt in PATH"
  fi

  if arduino-cli core list | awk '{print $1}' | grep -qx "esp32:esp32"; then
    ok "ESP32 Core bereits installiert"
    return
  fi

  log "Installiere fehlenden ESP32 Core …"
  arduino-cli core update-index --additional-urls "$ESP32_INDEX_URL"
  arduino-cli core install esp32:esp32 --additional-urls "$ESP32_INDEX_URL"
  ok "ESP32 Core installiert"
}

ensure_arduino_libs() {
  log "Arduino-Libraries prüfen (LovyanGFX, JPEGDEC, ArduinoJson) …"
  arduino-cli lib update-index >/dev/null 2>&1 || true

  local need_install=()
  for lib in LovyanGFX JPEGDEC ArduinoJson; do
    if ! arduino-cli lib list | awk '{print $1}' | grep -qx "$lib"; then
      need_install+=("$lib")
    fi
  done

  if [[ ${#need_install[@]} -gt 0 ]]; then
    arduino-cli lib install "${need_install[@]}"
    ok "Arduino-Libraries installiert: ${need_install[*]}"
  else
    ok "Arduino-Libraries bereits vorhanden"
  fi
}

[[ "$(id -u)" -eq 0 ]] && die "Bitte als normaler User ausführen, nicht root."
command -v git >/dev/null 2>&1 || die "git fehlt"
command -v systemctl >/dev/null 2>&1 || die "systemctl fehlt"

export PATH="$HOME/.local/bin:$PATH"

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
OLD_REV="$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || true)"
git -C "$INSTALL_DIR" fetch --all --prune -q
git -C "$INSTALL_DIR" reset --hard origin/main -q
NEW_REV="$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || true)"

OLD_VER="$(git_version_label "$OLD_REV")"
NEW_VER="$(git_version_label "$NEW_REV")"

if [[ -n "$OLD_REV" && "$OLD_REV" = "$NEW_REV" ]]; then
  log "Version ist aktuell ($NEW_VER)"
else
  log "Update angewendet: ${OLD_VER:-none} -> ${NEW_VER:-unknown}"
fi

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

# Toolchain für ESP-Workflows selbstheilend bereitstellen
ensure_arduino_cli
ensure_esp32_core
ensure_arduino_libs

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
