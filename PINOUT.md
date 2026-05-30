# Muffi Rahmen – PINOUT (ESP32-C6)

Stand: 2026-05-30

## Pflicht-Pins (aktuell im Code)

- **Servo Signal:** `GPIO3` (`SERVO_PIN`)
- **BOOT-Taster:** `GPIO9` (`BUTTON_PIN`) → Taster zwischen `GPIO9` und `GND`
- **RESET-Taster:** `EN/RST` Pin am ESP → Taster zwischen `EN/RST` und `GND`

## Nicht in externer Pin-Liste führen

- **Display-Pins** (fest auf dem C6-Board verdrahtet)
- **RGB-LED-Pin** (fest auf dem C6-Board)

## Verdrahtungs-Hinweise für geschlossenen Rahmen

- Für den später geschlossenen Rahmen **BOOT** und **RESET** als externe Taster auf den Sockel herausführen.
- Servo vorzugsweise mit **externer 5V-Versorgung** betreiben.
- Wichtig: **Gemeinsame Masse** zwischen ESP, Servo und externer Versorgung.

## Referenzen im Repo

- Firmware: `firmware/muffi-frame/muffi-frame.ino`
- Web UI Grafik: `runtime/ui-v2/index.html` (Tab "Motor")
