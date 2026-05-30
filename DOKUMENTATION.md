# Dokumentation – Muffi Frame Server + ESP

## Aktueller Stand (2026-05-17)

System läuft und ist aktuell funktionsfähig.

## Installer (neu)

- Linux-Installer: `install/linux/install-muffi-frame.sh`
- Update-Script: `install/linux/update-muffi-frame.sh`
- Uninstall-Script: `install/linux/uninstall-muffi-frame.sh`
- Zielgruppe aktuell: **DIY Linux/Raspberry Pi (Debian/Ubuntu)**
- Quickstart + Optionen stehen in `README.md`
- Installer + Update setzen automatisch auf:
  - `arduino-cli` (falls fehlend)
  - ESP32 Core `esp32:esp32`
  - damit sind USB-Erstflash und OTA ohne manuelle Toolchain-Nacharbeit nutzbar

## Code-Orte (Stand 2026-05-16)
- Server-Code (live): `projects/muffi-bilderrahmen/runtime/frame-server.py`
- Firmware-Code (live): `projects/muffi-bilderrahmen/firmware/muffi-frame/muffi-frame.ino`
- Kompatibilitätspfade (Symlink):
  - `/home/maika/frame-server.py`
  - `muffi-frame/`

### LED-Status (final)
- LED-Reihenfolge für dieses Gerät: **GRB**
- Doppelklick auf BOOT: funktioniert für Farbwechsel
- Standard-Farbkatalog: kräftiger Regenbogen (Rot, Orange, Gelb, Grün, Cyan, Blau, Violett, Magenta)
- Web-LED-Steuerung reagiert (On/Off, Helligkeit, Farbe, Reihenfolge)

### Weboberfläche
- Dashboard (neu, Version-UI): `http://<server>:8765/` (direkt auch unter `http://<server>:8765/version/`)
- Klassische Oberfläche (Fallback): `http://<server>:8765/classic`
- Galerie: `http://<server>:8765/gallery`

### Version-UI – neue Module (Stand 2026-05-17)
- Medien mit klarer Trennung:
  - **Lokal (stabil)**
  - **Netzwerkordner**
- Netzwerkordner-Flow:
  - UNC-Pfade für Windows-Nutzer werden unterstützt
  - Gleicher Share: UNC wird auf Linux-Mountpfad umgesetzt
  - Anderer Share: klare Admin-Meldung + Button für Share-Wechsel
- Firmware-Bereich:
  - **Server**: Update/Restart/Console
  - **ESP Erst-Flash (USB)**:
    - Port-Erkennung
    - Boot-Mode-Check
    - USB-Flash + Live-Console
  - **ESP On-the-fly (WLAN/OTA)**:
    - Erreichbarkeitscheck
    - Config-Senden an ESP
    - OTA-Update + Live-Console
    - Sync-Status (ob ESP Web-UI-Konfig bereits gezogen hat)

### Storage- und Share-APIs
- `GET /api/storage` – aktueller Storage-Zustand (active path/source, local/network health)
- `POST /api/storage` – Storage-Modus/Pfad setzen (`auto|local|network`)
- `POST /api/storage/share-check` – prüft, ob UNC im aktuellen Share liegt oder Admin-Sharewechsel braucht
- `POST /api/storage/share-switch` – versucht Share-Wechsel via System-Mount (Passwort nötig)
- `POST /api/storage/remount` – remountet den bestehenden Share

### Relevante API-Endpunkte
- `GET /api/list` – volle Dateiliste inkl. Metadaten
- `GET /list` – schlanke Liste für ESP-Kompatibilität
- `POST /api/upload?name=<dateiname>` – Bild-Upload
- `POST /api/delete` – Bild löschen
- `GET /api/config` / `POST /api/config` – Refresh-Intervall lesen/setzen
- `GET /api/upload-status` – Upload-Status für UI
- `GET /api/frame-state` – aktuell vom ESP gemeldetes Bild
- `POST /api/frame-state` – ESP meldet aktuell angezeigtes Bild
- `GET /api/wlan` / `POST /api/wlan` – WLAN/ESP/Server-Basiskonfig
- `POST /api/wlan/test` – ESP-Erreichbarkeit testen
- `POST /api/esp/prepare` – ESP-Konfig vorbereiten + Sync-Token setzen
- `GET /api/esp/sync-status` – Sync-Status (Token/ACK, letzter Pull)
- `GET /api/esp/update/status` / `POST /api/esp/update/start` – OTA Job-Status/Start
- `GET /api/esp/usb/status` – USB-Ports erkennen
- `POST /api/esp/usb/check-boot` – Boot-Modus per Port testen
- `GET /api/esp/usb/flash/status` / `POST /api/esp/usb/flash/start` – USB-Flash Job-Status/Start

## Verhalten „Aktuell auf dem Rahmen"

Die Server-UI zeigt nicht mehr nur das neueste Dateiobjekt, sondern den zuletzt vom ESP bestätigten Anzeigestand:
- Dateiname
- Orientierung (portrait/landscape)
- Position in der Liste (Index/Count)
- Bildvorschau in der Dashboard-Kachel

Damit entspricht die Anzeige auf der Webseite dem tatsächlich dargestellten Bild auf dem Rahmen.

## Betriebsnotiz

Stand heute wurde die Funktion live geprüft: Die Frame-State-Meldungen kommen an und die Dashboard-Anzeige aktualisiert sich korrekt.
