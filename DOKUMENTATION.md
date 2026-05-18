# Dokumentation – Muffi Frame Server + ESP

## Aktueller Stand (2026-05-17)

System läuft und ist aktuell funktionsfähig.

## Installer (neu)

- Linux-Installer: `install/linux/install-muffi-frame.sh`
- Zielgruppe aktuell: **DIY Linux/Raspberry Pi (Debian/Ubuntu)**
- Quickstart + Optionen stehen in `README.md`

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
- Dashboard (neu, UI v2): `http://<server>:8765/`
- Klassische Oberfläche (Fallback): `http://<server>:8765/classic`
- Galerie: `http://<server>:8765/gallery`

### UI v2 – neue Module (Stand 2026-05-17)
- Medien mit klarer Trennung:
  - **Lokal (stabil)**
  - **Netzwerkordner**
- Netzwerkordner-Flow:
  - UNC-Pfade für Windows-Nutzer werden unterstützt
  - Gleicher Share: UNC wird auf Linux-Mountpfad umgesetzt
  - Anderer Share: klare Admin-Meldung + Button für Share-Wechsel
- Firmware-Bereich:
  - OTA-Prüfung
  - USB-Flash-Hinweis

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

## Verhalten „Aktuell auf dem Rahmen"

Die Server-UI zeigt nicht mehr nur das neueste Dateiobjekt, sondern den zuletzt vom ESP bestätigten Anzeigestand:
- Dateiname
- Orientierung (portrait/landscape)
- Position in der Liste (Index/Count)
- Bildvorschau in der Dashboard-Kachel

Damit entspricht die Anzeige auf der Webseite dem tatsächlich dargestellten Bild auf dem Rahmen.

## Betriebsnotiz

Stand heute wurde die Funktion live geprüft: Die Frame-State-Meldungen kommen an und die Dashboard-Anzeige aktualisiert sich korrekt.
