# Muffi Frame (DIY)

Retro-futuristischer Bilderrahmen mit ESP + Python-Server.

## Unterstützte Installer-Zielplattform (aktuell)

- ✅ **Linux Server (Debian/Ubuntu)**
- ✅ **DIY Raspberry Pi (z. B. Raspberry Pi OS Lite 64-bit)**
- ❌ Windows/macOS Installer: noch nicht enthalten

## Schnellstart Installer (Linux / Raspberry Pi)

```bash
sudo apt-get update -y && sudo apt-get install -y git

git clone https://github.com/Onkels-Bastelbude/Muffi-Desktop-Rhamen.git
cd Muffi-Desktop-Rhamen
bash install/linux/install-muffi-frame.sh
```

Danach:
- Web UI: `http://<server-ip>:8765`
- Service Status: `systemctl --user status muffi-frame.service`
- Logs: `journalctl --user -u muffi-frame.service -f`

Der One-Click Installer richtet jetzt zusätzlich automatisch ein:
- `arduino-cli` (lokal unter `~/.local/bin`, falls noch nicht vorhanden)
- ESP32 Core `esp32:esp32` (inkl. Index-URL)

Damit sind Erst-Flash (USB) und OTA-Workflows direkt nach Installation nutzbar.

## Update

```bash
bash install/linux/update-muffi-frame.sh
```

## Uninstall

```bash
# nur Service entfernen (Code bleibt)
bash install/linux/uninstall-muffi-frame.sh

# komplett inkl. Installationsordner
bash install/linux/uninstall-muffi-frame.sh --purge
```

Optional für Headless Dauerbetrieb:

```bash
sudo loginctl enable-linger $USER
```

## Hinweise

- Installer ist idempotent (mehrfaches Ausführen = Update).
- Installiert nur benötigte Pakete, kein Full-Upgrade.
- Service läuft als **User-Service** (`systemd --user`).
- Das Update-Script hält Arduino-Toolchain ebenfalls automatisch aktuell/komplett.
