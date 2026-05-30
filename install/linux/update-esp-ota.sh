#!/usr/bin/env bash
set -euo pipefail

ESP_HOST="${ESP_HOST:-${1:-}}"
if [[ -z "$ESP_HOST" ]]; then
  echo "[error] ESP_HOST fehlt (z. B. ESP_HOST=192.168.50.79)"
  exit 2
fi

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SKETCH_DIR="${MUFFI_SKETCH_DIR:-$INSTALL_DIR/firmware/muffi-frame}"
BUILD_DIR="${MUFFI_BUILD_DIR:-$SKETCH_DIR/build}"
FQBN="${MUFFI_FQBN:-esp32:esp32:esp32c6}"
OTA_PORT="${ESP_OTA_PORT:-3232}"

ARDUINO_CLI="${ARDUINO_CLI:-}"

resolve_arduino_cli() {
  if [[ -n "$ARDUINO_CLI" && -x "$ARDUINO_CLI" ]]; then
    echo "$ARDUINO_CLI"
    return 0
  fi
  if command -v arduino-cli >/dev/null 2>&1; then
    command -v arduino-cli
    return 0
  fi
  local c
  for c in \
    "$HOME/.local/bin/arduino-cli" \
    "/usr/local/bin/arduino-cli" \
    "/usr/bin/arduino-cli"; do
    if [[ -x "$c" ]]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

echo "[info] install dir: $INSTALL_DIR"
echo "[info] sketch dir:  $SKETCH_DIR"
echo "[info] build dir:   $BUILD_DIR"
echo "[info] esp host:    $ESP_HOST"
echo "[info] fqbn:        $FQBN"

if [[ ! -d "$SKETCH_DIR" ]]; then
  echo "[error] Sketch-Verzeichnis nicht gefunden: $SKETCH_DIR"
  exit 2
fi

if ARDUINO_CLI_BIN="$(resolve_arduino_cli)"; then
  echo "[info] arduino-cli: $ARDUINO_CLI_BIN"
  echo "[info] kompiliere Firmware …"
  "$ARDUINO_CLI_BIN" compile --fqbn "$FQBN" --build-path "$BUILD_DIR" "$SKETCH_DIR"
else
  echo "[warn] arduino-cli nicht gefunden — überspringe Compile und nutze vorhandene Binärdatei"
fi

BIN_PATH="$BUILD_DIR/muffi-frame.ino.bin"
if [[ ! -f "$BIN_PATH" ]]; then
  echo "[error] Firmware-Binärdatei fehlt: $BIN_PATH"
  echo "[hint] Entweder arduino-cli installieren oder einmal lokal kompilieren, damit die .bin existiert"
  exit 3
fi

ESPOTA_PY="${ESPOTA_PY:-}"
if [[ -z "$ESPOTA_PY" ]]; then
  ESPOTA_PY="$(ls -1d "$HOME"/.arduino15/packages/esp32/hardware/esp32/*/tools/espota.py 2>/dev/null | sort -V | tail -n 1 || true)"
fi
if [[ -z "$ESPOTA_PY" || ! -f "$ESPOTA_PY" ]]; then
  echo "[error] espota.py nicht gefunden (ESP32 core installiert?)"
  exit 4
fi

echo "[info] ota upload …"
if [[ -n "${ESP_OTA_AUTH:-}" ]]; then
  python3 "$ESPOTA_PY" -i "$ESP_HOST" -p "$OTA_PORT" -a "$ESP_OTA_AUTH" -f "$BIN_PATH"
else
  python3 "$ESPOTA_PY" -i "$ESP_HOST" -p "$OTA_PORT" -f "$BIN_PATH"
fi

echo "[ok] ESP OTA Update abgeschlossen"
