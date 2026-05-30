#!/usr/bin/env bash
set -euo pipefail

ESP_HOST="${ESP_HOST:-${1:-}}"
if [[ -z "$ESP_HOST" ]]; then
  echo "[error] ESP_HOST fehlt (z. B. ESP_HOST=<ESP_HOST_ODER_IP>)"
  exit 2
fi

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SKETCH_DIR="${MUFFI_SKETCH_DIR:-$INSTALL_DIR/firmware/muffi-frame}"
BUILD_DIR="${MUFFI_BUILD_DIR:-$SKETCH_DIR/build}"
FQBN="${MUFFI_FQBN:-esp32:esp32:esp32c6}"
OTA_PORT="${ESP_OTA_PORT:-3232}"
ESPOTA_URL="${ESPOTA_URL:-https://raw.githubusercontent.com/espressif/arduino-esp32/master/tools/espota.py}"

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
  RELEASE_BIN="$INSTALL_DIR/firmware/releases/muffi-frame-latest.bin"
  if [[ -f "$RELEASE_BIN" ]]; then
    echo "[warn] Nutze vorgebaute Release-Binärdatei: $RELEASE_BIN"
    BIN_PATH="$RELEASE_BIN"
  else
    echo "[error] Firmware-Binärdatei fehlt: $BIN_PATH"
    echo "[hint] Entweder arduino-cli installieren oder firmware/releases/muffi-frame-latest.bin bereitstellen"
    exit 3
  fi
fi

resolve_espota_py() {
  if [[ -n "${ESPOTA_PY:-}" && -f "${ESPOTA_PY}" ]]; then
    echo "${ESPOTA_PY}"
    return 0
  fi

  local c
  for c in \
    "$HOME/.arduino15/packages/esp32/hardware/esp32"/*/tools/espota.py \
    "/home"/*/.arduino15/packages/esp32/hardware/esp32/*/tools/espota.py \
    "$INSTALL_DIR/.arduino15/packages/esp32/hardware/esp32"/*/tools/espota.py; do
    if [[ -f "$c" ]]; then
      echo "$c"
      return 0
    fi
  done

  return 1
}

ESPOTA_PY=""
if ESPOTA_PY="$(resolve_espota_py)"; then
  echo "[info] espota.py: $ESPOTA_PY"
else
  TMP_ESPOTA="$(mktemp /tmp/muffi-espota-XXXX.py)"
  if curl -fsSL "$ESPOTA_URL" -o "$TMP_ESPOTA"; then
    ESPOTA_PY="$TMP_ESPOTA"
    echo "[warn] espota.py nicht lokal gefunden — nutze Download: $ESPOTA_URL"
  else
    rm -f "$TMP_ESPOTA" >/dev/null 2>&1 || true
    echo "[error] espota.py nicht gefunden und Download fehlgeschlagen"
    exit 4
  fi
fi

echo "[info] ota upload …"
if [[ -n "${ESP_OTA_AUTH:-}" ]]; then
  python3 "$ESPOTA_PY" -i "$ESP_HOST" -p "$OTA_PORT" -a "$ESP_OTA_AUTH" -f "$BIN_PATH"
else
  python3 "$ESPOTA_PY" -i "$ESP_HOST" -p "$OTA_PORT" -f "$BIN_PATH"
fi

if [[ -n "${TMP_ESPOTA:-}" && -f "${TMP_ESPOTA}" ]]; then
  rm -f "${TMP_ESPOTA}" >/dev/null 2>&1 || true
fi

echo "[ok] ESP OTA Update abgeschlossen"
