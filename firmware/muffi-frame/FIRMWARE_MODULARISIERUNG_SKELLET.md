# Firmware Modularisierung – Büro-Skelettvorschlag (V1)

Ziel: `muffi-frame.ino` in stabile Funktionsblöcke trennen, ohne Over-Engineering.

## Leitprinzip
- Trenne nur Blöcke, die fachlich klar abgegrenzt sind und selten quer angefasst werden.
- Nicht nach UI-Tabs schneiden, sondern nach Firmware-Verantwortung.
- `main.ino` bleibt dünn (nur Orchestrierung in `setup()`/`loop()`).

## Vorschlag Dateistruktur

```text
firmware/muffi-frame/
├─ muffi-frame.ino              # setup/loop + Modul-Aufrufe
├─ app_state.h                  # zentraler gemeinsamer State (Struct + Extern)
├─ config_prefs.h/.cpp          # Preferences laden/speichern (WLAN, serverBase, LED)
├─ network_wlan.h/.cpp          # WiFi connect/reconnect + /api/wlan sync
├─ api_client.h/.cpp            # HTTP-Calls (/list, /api/config, /api/led, /api/upload-status)
├─ media_display.h/.cpp         # JPEG laden/anzeigen, Rotation, Statusscreen
├─ motor_servo.h/.cpp           # Servo-Move + Orientierungshilfe
├─ led_control.h/.cpp           # LED anwenden, zyklisch wechseln, state sync
├─ input_buttons.h/.cpp         # BOOT-ISR, Klicklogik, Seitentaste
└─ upload_overlay.h/.cpp        # Upload-Status-Overlay
```

## Schnitt (was wohin)

### 1) `app_state.h`
- Enthält `struct AppState` für gemeinsam genutzte Laufzeitdaten.
- Beispiel: `currentIdx`, `fileCount`, `refreshMs`, `serverBase`, `wifiSsid`, Upload/LED-Flags.

### 2) `config_prefs.*`
- `loadPrefs(AppState&)`
- `saveNetworkPrefs(const AppState&)`
- `saveLedPrefs(const AppState&)`

### 3) `network_wlan.*`
- `connectWiFi(AppState&, uint32_t timeoutMs)`
- `ensureWiFiConnected(AppState&)`
- `fetchWlanConfigFromServer(AppState&)`

### 4) `api_client.*`
- HTTP-Wrapper + JSON Parse pro Endpoint.
- Liefert klare DTOs/Result-Structs statt globalem Side-Effect.

### 5) `media_display.*`
- `refreshFileList(...)`
- `showImage(...)`
- `showStatus(...)`
- Kein WLAN-Management innen drin (nur Daten + Rendern).

### 6) `motor_servo.*`
- `servoInit()`
- `servoMovePortrait()` / `servoMoveLandscape()`

### 7) `led_control.*`
- `applyLed(...)`
- `refreshLedFromServer(...)`
- `reportLedState(...)`

### 8) `input_buttons.*`
- ISR + Debounce + Klick-Interpretation.
- Gibt Events zurück (`NEXT_IMAGE`, `LED_CYCLE`, ...), kein HTTP im Button-Modul.

### 9) `upload_overlay.*`
- `pollUploadStatus(...)`
- `showUploadProgress(...)`

## Migrationsreihenfolge (risikoarm)
1. `motor_servo` auslagern (klein, klar, wenig Abhängigkeit)
2. `input_buttons` auslagern
3. `led_control` auslagern
4. `config_prefs` + `network_wlan` auslagern
5. `media_display` + `api_client` zuletzt (größter Eingriff)

## Akzeptanzkriterien
- Kompiliert ohne Verhaltensänderung.
- Boot, WLAN-Reconnect, Bildwechsel, LED, Upload-Overlay funktionieren wie vorher.
- Neuinstallations-Flow bleibt stabil: Server setzen -> ESP verbindet -> Bilder kommen.

## Büro-Hinweis
- V1: modulare Trennung ja, aber begrenzt.
- Kein Refactor-Overkill vor den funktionalen V1-Tasks.
