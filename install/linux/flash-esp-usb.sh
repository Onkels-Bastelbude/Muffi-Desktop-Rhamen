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

if ! ARDUINO_CLI_BIN="$(resolve_arduino_cli)"; then
  echo "[error] arduino-cli nicht gefunden"
  echo "[hint] Für Erst-Flash bitte arduino-cli installieren oder ARDUINO_CLI auf den Binary-Pfad setzen"
  exit 127
fi

echo "[info] arduino-cli: $ARDUINO_CLI_BIN"

if [[ ! -d "$SKETCH_DIR" ]]; then
  echo "[error] Sketch-Verzeichnis nicht gefunden: $SKETCH_DIR"
  exit 2
fi

echo "[info] compile …"
"$ARDUINO_CLI_BIN" compile --fqbn "$FQBN" --build-path "$BUILD_DIR" "$SKETCH_DIR"

echo "[info] upload via usb …"
"$ARDUINO_CLI_BIN" upload --fqbn "$FQBN" -p "$ESP_PORT" --input-dir "$BUILD_DIR" "$SKETCH_DIR"

echo "[ok] usb-flash abgeschlossen"
