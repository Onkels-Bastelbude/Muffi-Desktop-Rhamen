# Dokumentation – Muffi Frame Server + ESP

## Aktueller Stand (2026-05-14)

System läuft und ist aktuell funktionsfähig.

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
- Dashboard: `http://<server>:8765/`
- Galerie: `http://<server>:8765/gallery`

### Relevante API-Endpunkte
- `GET /api/list` – volle Dateiliste inkl. Metadaten
- `GET /list` – schlanke Liste für ESP-Kompatibilität
- `POST /api/upload?name=<dateiname>` – Bild-Upload
- `POST /api/delete` – Bild löschen
- `GET /api/config` / `POST /api/config` – Refresh-Intervall lesen/setzen
- `GET /api/upload-status` – Upload-Status für UI
- `GET /api/frame-state` – aktuell vom ESP gemeldetes Bild
- `POST /api/frame-state` – ESP meldet aktuell angezeigtes Bild

## Verhalten „Aktuell auf dem Rahmen"

Die Server-UI zeigt nicht mehr nur das neueste Dateiobjekt, sondern den zuletzt vom ESP bestätigten Anzeigestand:
- Dateiname
- Orientierung (portrait/landscape)
- Position in der Liste (Index/Count)
- Bildvorschau in der Dashboard-Kachel

Damit entspricht die Anzeige auf der Webseite dem tatsächlich dargestellten Bild auf dem Rahmen.

## Betriebsnotiz

Stand heute wurde die Funktion live geprüft: Die Frame-State-Meldungen kommen an und die Dashboard-Anzeige aktualisiert sich korrekt.
