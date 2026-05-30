#!/usr/bin/env bash
# =============================================================================
# Muffi Frame – Linux Installer (v2)
# Unterstützt: Debian/Ubuntu/Raspberry Pi OS
# Idempotent: kann mehrfach ausgeführt werden (update-sicher)
# Verwendung:
#   bash install-muffi-frame.sh
#   REPO_URL=https://github.com/... bash install-muffi-frame.sh
# =============================================================================
set -euo pipefail

# ── Konfiguration (via Env überschreibbar) ──────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/Onkels-Bastelbude/Muffi-Desktop-Rhamen.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/muffi-frame}"
SERVICE_NAME="muffi-frame"
PORT="${PORT:-8765}"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_FILE="$HOME/.config/systemd/user/${SERVICE_NAME}.service"
ARDUINO_CLI_BIN="$HOME/.local/bin/arduino-cli"
ESP32_INDEX_URL="${ESP32_INDEX_URL:-https://espressif.github.io/arduino-esp32/package_esp32_index.json}"

# ── Farben & Logging ────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; BLU='\033[1;34m'; NC='\033[0m'
log()  { printf "${BLU}[+]${NC} %s\n" "$*"; }
ok()   { printf "${GRN}[✓]${NC} %s\n" "$*"; }
warn() { printf "${YEL}[!]${NC} %s\n" "$*"; }
die()  { printf "${RED}[✗] FEHLER:${NC} %s\n" "$*" >&2; exit 1; }

ensure_arduino_cli() {
  if command -v arduino-cli >/dev/null 2>&1; then
    ok "arduino-cli vorhanden ($(arduino-cli version | head -n1))"
    return
  fi

  log "arduino-cli fehlt → installiere lokal unter ~/.local/bin …"
  mkdir -p "$HOME/.local/bin"
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh
  export PATH="$HOME/.local/bin:$PATH"

  command -v arduino-cli >/dev/null 2>&1 || die "arduino-cli Installation fehlgeschlagen"
  ok "arduino-cli installiert ($(arduino-cli version | head -n1))"
}

ensure_esp32_core() {
  log "ESP32 Toolchain prüfen (esp32:esp32) …"
  if ! command -v arduino-cli >/dev/null 2>&1; then
    die "arduino-cli fehlt in PATH"
  fi

  if arduino-cli core list | awk '{print $1}' | grep -qx "esp32:esp32"; then
    ok "ESP32 Core bereits installiert"
    return
  fi

  log "Installiere ESP32 Core …"
  arduino-cli core update-index --additional-urls "$ESP32_INDEX_URL"
  arduino-cli core install esp32:esp32 --additional-urls "$ESP32_INDEX_URL"
  ok "ESP32 Core installiert"
}

# ── Fehler-Trap ─────────────────────────────────────────────────────────────
trap 'die "Unerwarteter Fehler in Zeile $LINENO. Installation abgebrochen."' ERR

# ── Sanity-Checks ───────────────────────────────────────────────────────────
[[ "$(id -u)" -eq 0 ]] && die "Nicht als root ausführen. Beispiel: bash install-muffi-frame.sh"

command -v sudo    >/dev/null 2>&1 || die "sudo fehlt – bitte installieren."
command -v apt-get >/dev/null 2>&1 || die "Dieser Installer benötigt apt-get (Debian/Ubuntu/Raspberry Pi OS)."
command -v systemctl >/dev/null 2>&1 || die "systemctl nicht gefunden – kein systemd?"

# ~/.local/bin in PATH für aktuelle Session
export PATH="$HOME/.local/bin:$PATH"

# ── Systempakete ─────────────────────────────────────────────────────────────
log "Systempakete prüfen / installieren …"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  git curl ca-certificates \
  python3 python3-venv python3-pip \
  cifs-utils smbclient samba-common-bin \
  >/dev/null 2>&1
ok "Systempakete bereit"

# ── Repository holen / aktualisieren ────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
  log "Bestehende Installation gefunden → Update …"
  git -C "$INSTALL_DIR" fetch --all --prune -q
  git -C "$INSTALL_DIR" reset --hard origin/main -q
  ok "Repository aktualisiert"
else
  log "Repository klonen nach $INSTALL_DIR …"
  git clone --depth=1 "$REPO_URL" "$INSTALL_DIR" -q
  ok "Repository geklont"
fi

# ── Python venv ──────────────────────────────────────────────────────────────
log "Python-Umgebung einrichten …"
python3 -m venv "$VENV_DIR" --upgrade-deps 2>/dev/null || python3 -m venv "$VENV_DIR"

REQUIREMENTS="$INSTALL_DIR/runtime/requirements.txt"
if [[ -f "$REQUIREMENTS" ]]; then
  "$VENV_DIR/bin/pip" install -q -r "$REQUIREMENTS"
  ok "Abhängigkeiten aus requirements.txt installiert"
else
  # Fallback: bekannte Mindest-Deps
  "$VENV_DIR/bin/pip" install -q --upgrade pillow
  ok "Fallback-Abhängigkeiten installiert (pillow)"
fi

# ── Arduino CLI + ESP32 Core (für Erst-Flash/OTA Workflows) ───────────────
ensure_arduino_cli
ensure_esp32_core

# ── Port-Konflikt prüfen ─────────────────────────────────────────────────────
if ss -tlnp 2>/dev/null | grep -q ":${PORT} " && \
   ! systemctl --user is-active "${SERVICE_NAME}.service" >/dev/null 2>&1; then
  warn "Port $PORT ist bereits belegt (anderer Prozess). Bitte prüfen."
fi

# ── systemd User Service ─────────────────────────────────────────────────────
log "systemd User Service einrichten …"
mkdir -p "$HOME/.config/systemd/user"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Muffi Frame Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR/runtime
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/runtime/frame-server.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "${SERVICE_NAME}.service" -q
systemctl --user restart "${SERVICE_NAME}.service"
ok "Service aktiviert und gestartet"

# ── Linger aktivieren (headless / ohne Login-Session) ────────────────────────
if ! loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
  log "Linger für $USER aktivieren (Autostart ohne Login) …"
  sudo loginctl enable-linger "$USER" 2>/dev/null || \
    warn "Linger konnte nicht gesetzt werden – Service startet ggf. erst nach Login."
fi

# ── Health-Check ─────────────────────────────────────────────────────────────
log "Warte auf Server-Start …"
TRIES=0
until curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; do
  TRIES=$((TRIES+1))
  [[ $TRIES -ge 12 ]] && { warn "Server antwortet nicht nach 12s – bitte Logs prüfen."; break; }
  sleep 1
done
[[ $TRIES -lt 12 ]] && ok "Server erreichbar"

# ── URL ermitteln ─────────────────────────────────────────────────────────────
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -z "${HOST_IP:-}" ]] && HOST_IP="<server-ip>"

HOSTNAME_LOCAL="$(hostname -s 2>/dev/null).local"

# ── Ergebnis ──────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
printf "${GRN}✅ Muffi Frame Installation fertig!${NC}\n"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
printf "  ${BLU}URL (IP):${NC}       http://${HOST_IP}:${PORT}\n"
printf "  ${BLU}URL (mDNS):${NC}     http://${HOSTNAME_LOCAL}:${PORT}\n"
echo ""
printf "  ${BLU}Service-Status:${NC} systemctl --user status ${SERVICE_NAME}\n"
printf "  ${BLU}Logs live:${NC}      journalctl --user -u ${SERVICE_NAME} -f\n"
printf "  ${BLU}Neustart:${NC}       systemctl --user restart ${SERVICE_NAME}\n"
echo ""
