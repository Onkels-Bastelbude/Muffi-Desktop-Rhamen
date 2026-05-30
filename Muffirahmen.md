# Muffirahmen – Projektstatus

Stand: 2026-05-30

## Aktueller Sprint (kurz)
- **Done:** Vorschau, LED, WLAN-Settings, Server-Update, ESP Erst-Flash, ESP OTA/On-the-fly, Sync-Status, Motor-API + Motor-UI + ESP-Motor-Sync (Basis)
- **Baustelle:** Medien, Motor-Feintuning
- **Nächster Schritt:** Medien-Flow final glätten, danach Motor-Feinschliff (Kalibrierlogik/UX)

## Leitregel (ab sofort)
- Bei Planung, UI-Flow, Texten und Entscheidungen **immer vom Szenario „Neuinstallation / Erstinstallation“** ausgehen.
- Jeder zentrale Flow muss für einen neuen Nutzer ohne Vorwissen funktionieren (Server setzen → ESP koppeln → Verifizieren).
- Fallbacks und Statusanzeigen so bauen, dass sie auch ohne Bestandswissen sofort verständlich sind.

## Erledigt (aktueller Stand)
- Web UI v2 läuft stabil
- Vorschau läuft
- LED-Steuerung läuft
- WLAN-Settings + ServerBase-Flow läuft
- Server-Update-Flow läuft
- ESP Erst-Flash (USB) läuft
- ESP On-the-fly OTA läuft
- ESP Sync-Status im UI bestätigt (Config wird empfangen)

## Aktuelle Baustellen
1. **Medien** (Flow/Handling final glätten)
2. **Motor-Feintuning** (Kalibrierung/UX fertigziehen)

## Nächster konkreter Schritt
- Medien-Flow abschließen (inkl. robuster Quellenwechsel), danach Motor-Bereich auf Feinschliff bringen.

## Büro-Fazit (2026-05-18) – Hybrid Quelle + Setup-Flow
- **Bewertung:** 🟡 Gelb-Grün (sinnvoll und machbar, wenn sauber begrenzt)
- **Beschlussvorschlag:** Netzwerkordner bleibt Primärquelle, lokaler Ordner ist robuster Fallback.
- **Web-UI Soll/Ist-Prinzip:**
  - Soll (Pi): konfigurierte `serverBase` + gewünschte Quelle
  - Ist (ESP): zuletzt gemeldete aktive `serverBase` + aktuelles Bild/Quelle
- **V1-Mindestumfang:**
  1. Setup-Wizard „Server + ESP verbinden“ (Speichern, Test, Anwenden, Verifizieren)
  2. Statuskarte mit Drift-Hinweis ("ESP nutzt noch alten Server")
  3. Fallback-Regel klar anzeigen (Netzwerk down → lokal)
- **Nicht für V1:** persistenter Bild-Cache auf ESP (mehr Komplexität/Fehlerbilder)

## Büro-Fazit (2026-05-18) – Firmware modularisieren ohne Verwirrung
- **Bewertung:** 🟢 Grün (klare Wartbarkeitsgewinne bei geringem Risiko, wenn in groben Blöcken getrennt)
- **Leitlinie:** Nicht nach UI-Tabs schneiden, sondern nach stabilen Firmware-Verantwortungen.
- **Beschlussvorschlag:** `muffi-frame.ino` in 8-9 Module trennen; `main.ino` bleibt Orchestrierung.
- **Ablage Skelett:** `projects/muffi-bilderrahmen/firmware/muffi-frame/FIRMWARE_MODULARISIERUNG_SKELLET.md`
- **Reihenfolge:** zuerst kleine, stabile Blöcke (`motor_servo`, `input_buttons`, `led_control`), große Blöcke (`media_display`, `api_client`) zuletzt.
- **Status aktuell:** Auf Wunsch geparkt bis nach V1-Stabilisierung (kein Refactor jetzt).

## Offene Fragen
- Keine kritischen offenen Fragen; Fokus liegt auf den 2 Baustellen (Medien, Motor).

## Blocker
- Keine harten technischen Blocker bekannt

## Betriebsdaten (aktuell bekannt)
- Server-Basis: `http://192.168.50.68:8765`
- ESP (zuletzt): `192.168.50.79`
- SMB-Mount: `/mnt/muffi`
- Live-Server-Code: `projects/muffi-bilderrahmen/runtime/frame-server.py`
- Live-Firmware-Code: `projects/muffi-bilderrahmen/firmware/muffi-frame/muffi-frame.ino`
- Pinout-Doku: `projects/muffi-bilderrahmen/PINOUT.md`

## Hardware-Pin-Merkpunkte (für später geschlossenen Rahmen)
- Servo Signal: `GPIO3`
- BOOT Taster extern: `GPIO9` ↔ `GND`
- RESET Taster extern: `EN/RST` ↔ `GND`
- Ziel: BOOT/RESET auf Sockel auslagern (Service-Zugang ohne Rahmen zu öffnen)

## GitHub (gemeinsamer Projektstand)
- Repo: `https://github.com/Onkels-Bastelbude/Muffi-Desktop-Rhamen`
- SSH: `git@github.com:Onkels-Bastelbude/Muffi-Desktop-Rhamen.git`

## Neue Notizen von Andre (Strategie, 2026-05-16)

### Vision / Produktbild
- Retro-futuristische Smart-Frame Plattform „Muffi Rahmen“
- Ziel: benutzerfreundlich, mobil optimiert, visuell einzigartig (70er Retro-Futurismus)
- DIY-Produkt mit Software, ESP-Firmware, 3D-Druckdateien

### Design-Ideen
- Stil: organische Formen, ovale Fenster, Konsolenoptik, Tapetenmuster, Psychedelic-Elemente
- UI: Darkmode, kontrastreiche Menüs, Glow/Hover-Effekte, abgerundete Panels, optionale CRT-Scanlines
- Farbwelt: Orange/Grün/Braun/Senf/Ocker/Beige/Terrakotta/Petrol/Cremeweiß (+ Disco-Varianten)

### UI/Layout-Ideen
- Rechtes Menü: Server, ESP Flash, WLAN, Motor, Konfig, Medien, LED, Spezialmodi, Firmware, Upload, Netzwerkordner
- Mitte: dynamischer Arbeitsbereich je Menüpunkt
- Links: Live-Vorschau Rahmen + LED-Farbe/Helligkeit/Effekte

### Mobile-Anforderungen
- Voll responsiv (Smartphone/Tablet/Desktop)
- Touch-freundlich, einklappbare Panels, mobile Live-Vorschau

### Setup / Installation
- Ziel: sehr einfache Einrichtung für Anfänger
- Idee: Installer setzt lokalen Server auf
- Später optional: GitHub-Download, lokale Installation, Auto-Updates

### ESP-Workflow
- Erstinstallation per USB oder SD
- WLAN-Daten beim Setup
- Danach Steuerung über Web („auf Rahmen laden“, Einstellungen senden, Neustart, Sync)

### Medien & Konfiguration
- Upload via Handy/PC/Browser
- Quelle optional auch Netzwerkordner (NAS/Share/lokaler Ordner)
- Einfache Maske: IP, Pfad, Benutzer optional, Test, Speichern

### Motor
- Rotation, Winkel, Kalibrierung, Geschwindigkeit, Speichern, an ESP senden
- Optional: Live-Test/Vorschau

### Spezialmodi
- Lavalampe (Hochformat, Loop bis ~5 min, Farbvarianten, nur Modusausgabe)
- Kaminfeuer (Querformat, Flammen-Loop, immersiv)
- Optional SD-Sync für große Loops/lokale Wiedergabe

### Übergänge
- Text durch animierte lila Ring-/Kreiswellen ersetzen (weich, neonartig)

### Architektur-Ideen
- Backend: Node.js oder FastAPI oder Electron
- Frontend: React/Next.js/Tailwind/Framer Motion
- ESP-Kommunikation: REST/WebSocket, OTA, Live-Status

### Hinweis zur Einordnung
- Diese Notizen sind **Ideen-/Strategie-Sammlung**.
- Für V1 gilt weiterhin: bewusst einfach starten (Stabilität vor Feature-Fülle).
