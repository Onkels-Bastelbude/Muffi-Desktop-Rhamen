#!/usr/bin/env bash
set -euo pipefail

ESP_PORT="${ESP_PORT:-${1:-}}"
if [[ -z "$ESP_PORT" ]]; then
  echo "[error] ESP_PORT fehlt (z. B. ESP_PORT=/dev/ttyACM0)"
  exit 2
fi

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SKETCH_DIR="${MUFFI_SKETCH_DIR:-$INSTALL_DIR/firmware/muffi-frame}"
BUILD_DIR="${MUFFI_BUILD_DIR:-$SKETCH_DIR/build}"
FQBN="${MUFFI_FQBN:-esp32:esp32:esp32c6}"
ARDUINO_CLI="${ARDUINO_CLI:-}"

resolve_esptool() {
  local c
  for c in \
    "$HOME/.arduino15/packages/esp32/tools/esptool_py"/*/esptool \
    "/usr/local/bin/esptool" \
    "/usr/bin/esptool"; do
    if [[ -x "$c" ]]; then
      echo "$c"
      return 0
    fi
  done
  if command -v esptool >/dev/null 2>&1; then
    command -v esptool
    return 0
  fi
  return 1
}

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

echo "[info] erst-flash via usb"
echo "[info] port:       $ESP_PORT"
echo "[info] sketch dir: $SKETCH_DIR"
echo "[info] fqbn:       $FQBN"

if [[ ! -d "$SKETCH_DIR" ]]; then
  echo "[error] Sketch-Verzeichnis nicht gefunden: $SKETCH_DIR"
  exit 2
fi

if ARDUINO_CLI_BIN="$(resolve_arduino_cli)"; then
  echo "[info] arduino-cli: $ARDUINO_CLI_BIN"
  echo "[info] compile …"
  "$ARDUINO_CLI_BIN" compile --fqbn "$FQBN" --build-path "$BUILD_DIR" "$SKETCH_DIR"

  echo "[info] upload via usb …"
  "$ARDUINO_CLI_BIN" upload --fqbn "$FQBN" -p "$ESP_PORT" --input-dir "$BUILD_DIR" "$SKETCH_DIR"
else
  echo "[warn] arduino-cli nicht gefunden — nutze merged Release-Binärdatei + esptool"
  RELEASE_MERGED_BIN="$INSTALL_DIR/firmware/releases/muffi-frame-latest.merged.bin"
  if [[ ! -f "$RELEASE_MERGED_BIN" ]]; then
    echo "[error] Release-Binärdatei fehlt: $RELEASE_MERGED_BIN"
    echo "[hint] Bitte arduino-cli installieren ODER firmware/releases/muffi-frame-latest.merged.bin bereitstellen"
    exit 127
  fi

  if ! ESPTOOL_BIN="$(resolve_esptool)"; then
    echo "[error] esptool nicht gefunden"
    echo "[hint] Installiere esp32 core tools (esptool_py), dann erneut versuchen"
    exit 127
  fi

  echo "[info] esptool: $ESPTOOL_BIN"
  echo "[info] write_flash 0x0 $RELEASE_MERGED_BIN"
  "$ESPTOOL_BIN" --chip esp32c6 --port "$ESP_PORT" --baud 460800 write_flash 0x0 "$RELEASE_MERGED_BIN"
fi

echo "[ok] usb-flash abgeschlossen"
