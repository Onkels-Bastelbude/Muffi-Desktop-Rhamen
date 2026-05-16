# Arbeitsprotokoll – Muffi Bilderrahmen

## 2026-05-16

- Projektstruktur vereinheitlicht (alles in `projects/muffi-bilderrahmen/` gebündelt):
  - Server nach `runtime/frame-server.py` verschoben.
  - Firmware-Workspace nach `firmware/muffi-frame/` verschoben.
- Legacy-Pfade als Symlinks belassen für Kompatibilität:
  - `/home/maika/frame-server.py` → Projektpfad
  - `muffi-frame/` → Projektpfad
- Laufzeit geprüft: `frame-server.service` ist aktiv (Port 8765 lauscht).

## 2026-05-14

- Upload-Funktion stabilisiert und getestet (Web-Upload + Server-Speicherung).
- Löschfunktion ergänzt:
  - Dashboard: Löschen des aktuell gezeigten Bildes.
  - Galerie: Löschen pro Bild.
  - API: `POST /api/delete`.
- Galerie-Löschproblem behoben (JavaScript-Handling/Confirm korrigiert).
- ESP-Refresh-Verhalten überarbeitet (kein Festhängen auf gelöschtem Bild).
- Dashboard umgebaut:
  - Bereich „Neuestes Bild“ entfernt.
  - Neuer Bereich „Aktuell auf dem Rahmen“ zeigt den echten ESP-Anzeigestand.
- Neue Frame-State-Schnittstelle umgesetzt:
  - `POST /api/frame-state` (ESP meldet aktuellen Stand)
  - `GET /api/frame-state` (Weboberfläche liest aktuellen Stand)
- Firmware erweitert: ESP meldet nach erfolgreichem Rendern `filename`, `orientation`, `index`, `count` an den Server.
- OTA-Update auf ESP (`<lokale-esp-ip>`) durchgeführt.
- Live verifiziert: Anzeige „Aktuell auf dem Rahmen“ funktioniert derzeit korrekt.
- LED-Steuerung finalisiert:
  - Doppelklick auf BOOT funktioniert zuverlässig.
  - Farbwechsel auf kräftigen Regenbogen-Katalog umgestellt.
  - LED-Reihenfolge GRB als korrekt bestätigt.
  - Websteuerung (Helligkeit/Farbe) reagiert korrekt.
