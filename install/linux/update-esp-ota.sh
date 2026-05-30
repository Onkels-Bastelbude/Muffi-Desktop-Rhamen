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

ARDUINO_CLI="${ARDUINO_CLI:-arduino-cli}"

echo "[info] install dir: $INSTALL_DIR"
echo "[info] sketch dir:  $SKETCH_DIR"
echo "[info] build dir:   $BUILD_DIR"
echo "[info] esp host:    $ESP_HOST"
echo "[info] fqbn:        $FQBN"

if [[ ! -d "$SKETCH_DIR" ]]; then
  echo "[error] Sketch-Verzeichnis nicht gefunden: $SKETCH_DIR"
  exit 2
fi

echo "[info] kompiliere Firmware …"
"$ARDUINO_CLI" compile --fqbn "$FQBN" --build-path "$BUILD_DIR" "$SKETCH_DIR"

BIN_PATH="$BUILD_DIR/muffi-frame.ino.bin"
if [[ ! -f "$BIN_PATH" ]]; then
  echo "[error] Firmware-Binärdatei fehlt: $BIN_PATH"
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
