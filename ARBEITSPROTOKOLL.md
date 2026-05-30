# Arbeitsprotokoll – Muffi Bilderrahmen

## 2026-05-30

- Firmware-/ESP-Bereich in UI stark erweitert und vereinfacht:
  - Server-Steuerung getrennt von ESP-Steuerung
  - ESP Erst-Flash (USB): Port erkennen, Boot-Check, Flash-Start + Konsole
  - ESP On-the-fly (WLAN/OTA): Erreichbarkeit, OTA, Config-Sync + Konsole
- One-Click/Update-Skripte gehärtet:
  - `arduino-cli` + ESP32-Core Auto-Setup
  - benötigte Arduino-Libraries Auto-Install (`LovyanGFX`, `JPEGDEC`, `ArduinoJson`)
  - OTA/Flash-Fallbacks für fehlende lokale Tools
- Sync-Problem gelöst (ESP hat Web-UI-Daten empfangen bestätigt).
- UI-Styling im Firmware-Bereich auf konsistenten 70s-Retro-Look gebracht (inkl. Step-Frames + Status-Karten).
- Aktueller Fokus reduziert auf zwei Baustellen: **Medien** und **Motor**.

## 2026-05-17

- Neue UI (`/ui-v2`) mit Bestands-Backend verbunden.
- LED-Funktionen im neuen UI verifiziert: Ein/Aus, Helligkeit, Farbe, Reihenfolge und Katalogwechsel funktionieren.
- WLAN-Modul live angebunden:
  - API: `GET/POST /api/wlan`
  - Verbindungstest: `POST /api/wlan/test` (TCP-Test auf ESP-Host)
  - UI: SSID, Passwort, ESP-Host, Server-URL speichern + Test-Button
- Firmware erweitert für WLAN nach Notizen:
  - lädt/speichert WLAN + Server-Base in Preferences
  - holt Konfig regelmäßig von `/api/wlan`
  - nutzt dynamische `serverBase` für alle API-Aufrufe
- Build erfolgreich mit `arduino-cli`.
- Flash-Versuch gestartet, aktuell blockiert: `Failed to connect to ESP32-C6: No serial data received` auf `/dev/ttyAMA10`.
- Medien-Upload Fehler analysiert und behoben:
  - Ursache: `/mnt/muffi` war nicht schreibbar (`Permission denied`).
  - Fix: Server nutzt automatisch lokalen Fallback-Ordner, wenn Netzwerkpfad nicht schreibbar ist.
  - Fallback aktiv: `projects/muffi-bilderrahmen/runtime/photos`
  - Upload wieder erfolgreich verifiziert (`HTTP 200`).
- Medien-UI erweitert (Büro-Entscheid umgesetzt):
  - Zwei klar getrennte Kategorien im Medien-Bereich: **Lokal (stabil)** und **Netzwerkordner**.
  - Neuer API-Bereich `GET/POST /api/storage` für Pfadwahl und Modus (`auto|local|network`).
  - Buttons: „Diesen Ordner nutzen“, „Netzwerkordner nutzen“, „Pfad speichern“.
  - Klare Statusanzeige pro Kategorie (erreichbar/schreibbar/nicht erreichbar) + aktive Quelle hervorgehoben.
- Share-Wechsel-Logik nachgeschärft:
  - UNC-Pfade werden auf **gleichen Share** korrekt in Unterordner von `/mnt/muffi` gemappt.
  - Bei **anderem Share** wird Pfad nicht übernommen (kein falscher Unterordner mehr).
  - UI-Button ergänzt: **„Share wechseln (Admin)“**.
  - Neue Prüf-API: `POST /api/storage/share-check` (zeigt klar, ob Admin-Remount nötig ist).

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
