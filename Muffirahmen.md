# Muffirahmen – Projektstatus

Stand: 2026-05-17

## Heute erledigt (letzter bestätigter Stand)
- Neue UI v2 als Startseite live
- Medien-Bereich mit 2 klaren Quellen (Lokal/Netzwerkordner)
- UNC-Unterstützung für Windows-Nutzer inkl. Hilfe-`?`
- Share-Check und Share-Wechsel-Flow ergänzt (Admin-Passwort erforderlich)
- Netzwerkordnerwechsel-Button + Passwort-Modal verbessert
- WLAN-Modul + LED-Modul stabil im neuen UI verifiziert

## Nächster Schritt (V1 einfach)
1. Motor-Basisfunktionen sauber im UI (Winkel, Geschwindigkeit, Speichern, Senden)
2. Share-Wechsel robust gegen alle Mount-Sonderfälle härten (System-Mount-Handling)
3. V1-Setup-Checkliste für Nutzer fertigstellen

## Offene Fragen
- Exakte V1-Grenze final abnicken (was bleibt draußen)
- Reihenfolge: zuerst UI aufräumen oder zuerst Motor-Konfig

## Blocker
- Keine harten technischen Blocker bekannt

## Betriebsdaten (aktuell bekannt)
- Server-Basis: `http://frame-server.local:8765` (Beispiel)
- ESP (zuletzt): `<lokale-esp-ip>`
- SMB-Mount: `<lokaler-mountpfad>`
- Live-Server-Code: `projects/muffi-bilderrahmen/runtime/frame-server.py`
- Live-Firmware-Code: `projects/muffi-bilderrahmen/firmware/muffi-frame/muffi-frame.ino`

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
