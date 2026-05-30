# Dokumentation – Muffi Frame Server + ESP

## Aktueller Stand (2026-05-31)

System läuft produktiv im Heimnetz. Kernfunktionen sind verifiziert:
- Vorschau/Anzeige
- LED-Steuerung
- WLAN-/Server-Konfiguration
- Server-Update aus Web-UI
- ESP Erst-Flash (USB)
- ESP OTA/On-the-fly Update
- ESP Sync-Status („Config empfangen")
- Motor-Steuerung (UI + API + Firmware-Sync, inkl. Testfunktionen)

## Aktuelle Baustellen
- **Medien** (Flow/Handling final glätten)

## Installer / Betrieb
- Linux-Installer: `install/linux/install-muffi-frame.sh`
- Update-Script: `install/linux/update-muffi-frame.sh`
- Uninstall-Script: `install/linux/uninstall-muffi-frame.sh`
- Zielplattform: Debian/Ubuntu/Raspberry Pi OS

Der Installer/Updater setzt automatisch auf:
- `arduino-cli` (falls fehlend)
- ESP32 Core `esp32:esp32`
- Arduino-Libraries: `LovyanGFX`, `JPEGDEC`, `ArduinoJson`

Damit funktionieren USB-Erstflash und OTA ohne manuelle Toolchain-Nacharbeit.

## Live-Code-Orte
- Server: `runtime/frame-server.py`
- Firmware: `firmware/muffi-frame/muffi-frame.ino`

## Weboberfläche
- Haupt-UI: `http://<server>:8765/` (Alias: `/ui-v2/`)
- Classic-Fallback: `http://<server>:8765/classic`
- Galerie: `http://<server>:8765/gallery`

### Firmware-Bereich (UI)
- **Server**
  - Update starten
  - Neustart
  - Konsole
- **ESP Erst-Flash (USB)**
  - USB-Port erkennen
  - Boot-Modus prüfen
  - Erst-Flash starten
  - Live-Konsole
- **ESP On-the-fly (WLAN/OTA)**
  - WLAN/Server/ESP-Host konfigurieren
  - optionaler Fallback-Server (konfigurierbar)
  - Sync-Timeout (konfigurierbar)
  - ESP erreichbar prüfen
  - OTA starten
  - Config an ESP senden
  - Sync-Status + Live-Konsole

## Storage / Medien
- Lokaler Speicher + Netzwerkordner
- UNC-Unterstützung (Windows)
- Share-Check/Share-Switch/Remount im UI

## Relevante API-Endpunkte
- `GET /api/status`
- `GET /api/list`, `GET /list`
- `POST /api/upload?name=...`, `POST /api/delete`
- `GET/POST /api/config`
- `GET /api/upload-status`
- `GET/POST /api/frame-state`
- `GET/POST /api/wlan`, `POST /api/wlan/test`
- `GET/POST /api/storage`
- `POST /api/storage/share-check`, `POST /api/storage/share-switch`, `POST /api/storage/remount`
- `GET/POST /api/motor`
- `POST /api/esp/prepare`, `GET /api/esp/sync-status`
- `POST /api/esp/update/start`, `GET /api/esp/update/status`
- `GET /api/esp/usb/status`, `POST /api/esp/usb/check-boot`
- `POST /api/esp/usb/flash/start`, `GET /api/esp/usb/flash/status`

## Betriebsnotiz
Heute-Stand: End-to-end (USB-Flash → OTA → Sync → Bildanzeige) erfolgreich getestet.
