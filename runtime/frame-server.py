#!/usr/bin/env python3
"""
Muffi Frame Server ❤️
Erkennt automatisch Hoch/Querformat und skaliert passend für ESP32-C6 Display
"""

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageOps
from urllib.parse import unquote, quote, parse_qs, urlparse
from html import escape
import os, io, json, time, threading, re, socket, subprocess, tempfile, shutil
from pathlib import Path

PHOTO_DIR  = "/mnt/muffi"
FALLBACK_PHOTO_DIR = str(Path.home() / ".muffi" / "photos")
PORT       = 8765
DISPLAY_W  = 172   # Hochformat Breite
DISPLAY_H  = 320   # Hochformat Höhe

CONFIG_PATH = str(Path.home() / ".frame-server-config.json")
LOCAL_SHARE_CREDENTIALS_PATH = str(Path.home() / ".muffi-credentials")
DEFAULT_REFRESH_MS = 5 * 60 * 1000
MIN_REFRESH_MS = 10 * 1000
MAX_REFRESH_MS = 24 * 60 * 60 * 1000
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
RUNTIME_DIR = os.path.dirname(os.path.realpath(__file__))
UI_V2_DIR = os.path.join(RUNTIME_DIR, "ui-v2")
UI_V2_FILES = {
    "index.html": "text/html; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "script.js": "application/javascript; charset=utf-8",
    "bg-loop.gif": "image/gif",
    "motor-wiring.jpg": "image/jpeg",
}

LED_COLORS = [
    {"name": "Rot", "hex": "#FF0000"},
    {"name": "Orange", "hex": "#FF5000"},
    {"name": "Gelb", "hex": "#FFFF00"},
    {"name": "Grün", "hex": "#00FF00"},
    {"name": "Cyan", "hex": "#00FFFF"},
    {"name": "Blau", "hex": "#0000FF"},
    {"name": "Violett", "hex": "#8000FF"},
    {"name": "Magenta", "hex": "#FF00B4"},
]

ORIENTATION_CACHE = {}
UPLOAD_LOCK = threading.Lock()
UPLOAD_STATUS = {
    "active": False,
    "phase": "idle",         # idle|uploading|done|error
    "progress": 0,
    "filename": "",
    "message": "",
    "updatedAt": 0.0,
}

FRAME_STATE_LOCK = threading.Lock()
FRAME_STATE = {
    "filename": "",
    "orientation": "",
    "index": -1,
    "count": 0,
    "updatedAt": 0.0,
    "source": "",
    "exists": False,
}

LED_LOCK = threading.Lock()
CONFIG_LOCK = threading.Lock()

UPDATE_LOCK = threading.Lock()
UPDATE_STATE = {
    "phase": "idle",          # idle | running | done | error
    "lines": [],
    "exitCode": None,
    "startedAt": 0.0,
    "finishedAt": 0.0,
    "scriptPath": "",
}

ESP_UPDATE_LOCK = threading.Lock()
ESP_UPDATE_STATE = {
    "phase": "idle",          # idle | running | done | error
    "lines": [],
    "exitCode": None,
    "startedAt": 0.0,
    "finishedAt": 0.0,
    "scriptPath": "",
    "espHost": "",
}

ESP_USB_FLASH_LOCK = threading.Lock()
ESP_USB_FLASH_STATE = {
    "phase": "idle",          # idle | running | done | error
    "lines": [],
    "exitCode": None,
    "startedAt": 0.0,
    "finishedAt": 0.0,
    "scriptPath": "",
    "port": "",
}


def safe_isdir(path):
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def safe_ismount(path):
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def ensure_local_photo_dir():
    os.makedirs(FALLBACK_PHOTO_DIR, exist_ok=True)
    return FALLBACK_PHOTO_DIR


def is_writable_dir(path):
    return safe_isdir(path) and os.access(path, os.W_OK | os.X_OK)


def sanitize_storage_config(raw):
    raw = raw or {}
    mode = str(raw.get("mode", "auto") or "auto").strip().lower()
    if mode not in ("auto", "local", "network"):
        mode = "auto"

    network_path = str(raw.get("networkPath", PHOTO_DIR) or PHOTO_DIR).strip()
    if not network_path.startswith("/"):
        network_path = PHOTO_DIR
    network_path = os.path.abspath(network_path)[:256]

    local_path = str(raw.get("localPath", FALLBACK_PHOTO_DIR) or FALLBACK_PHOTO_DIR).strip()
    if not local_path.startswith("/"):
        local_path = FALLBACK_PHOTO_DIR
    local_path = os.path.abspath(local_path)[:256]

    raw_network_path = str(raw.get("rawNetworkPath", "") or "").strip()[:256]
    if not raw_network_path:
        raw_network_path = network_path

    return {
        "mode": mode,
        "networkPath": network_path,
        "rawNetworkPath": raw_network_path,
        "localPath": local_path,
        "updatedAt": float(raw.get("updatedAt") or 0.0),
    }


def normalize_network_path_input(value):
    raw = str(value or "").strip()
    if not raw:
        return PHOTO_DIR, "", ""

    # Windows UNC oder Backslash-Eingaben automatisch auf Linux-Mountpfad mappen.
    # Beispiel: \\SERVER\Share\Ordner A\2012 -> /mnt/muffi/Ordner A/2012
    if raw.startswith("\\\\") or "\\" in raw or (raw.startswith("//") and not raw.startswith("/mnt/")):
        cleaned = raw.replace("/", "\\").strip("\\")
        parts = [p.strip() for p in cleaned.split("\\") if p.strip()]
        # UNC-Struktur: \\server\share\optional\sub\path
        rel_parts = parts[2:] if len(parts) >= 3 else []
        rel_path = "/".join(rel_parts)
        hint = "UNC erkannt: Server/Share wird auf Linux nicht direkt genutzt; aktiv ist nur der gemountete Pfad unter /mnt/muffi."
        if rel_path:
            mapped = os.path.abspath(os.path.join(PHOTO_DIR, rel_path))
            return mapped[:256], raw, hint
        return PHOTO_DIR, raw, hint

    if raw.startswith("/"):
        return os.path.abspath(raw)[:256], "", ""

    return PHOTO_DIR, raw, ""


def _decode_mount_field(s):
    # /proc/*/mounts escaped fields
    return str(s or "").replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def get_network_mount_source_for_photo_dir():
    try:
        with open("/proc/self/mounts", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                src = _decode_mount_field(parts[0])
                mnt = _decode_mount_field(parts[1])
                fstype = parts[2]
                if mnt == PHOTO_DIR and fstype.lower() == "cifs":
                    return src
    except Exception:
        pass
    return ""


def is_path_on_active_network_share(path):
    mount_src = get_network_mount_source_for_photo_dir()
    if not mount_src:
        return False
    try:
        base = os.path.abspath(PHOTO_DIR).rstrip("/")
        target = os.path.abspath(path or "")
        return target == base or target.startswith(base + "/")
    except Exception:
        return False


def parse_unc_path(value):
    raw = str(value or "").strip()
    if not raw:
        return None

    # Windows-Laufwerkspfad ist kein UNC (z. B. C:\Users\...)
    if re.match(r"^[A-Za-z]:([\\/]|$)", raw):
        return None

    # Für UNC erwarten wir ein führendes \\ oder //
    if not (raw.startswith("\\\\") or raw.startswith("//")):
        return None

    cleaned = raw.replace("/", "\\").strip("\\")
    parts = [p.strip() for p in cleaned.split("\\") if p.strip()]
    if len(parts) < 2:
        return None
    return {
        "server": parts[0],
        "share": parts[1],
        "subparts": parts[2:] if len(parts) > 2 else [],
    }


def analyze_network_path_input(value):
    raw = str(value or "").strip()
    if not raw:
        return {
            "mappedPath": PHOTO_DIR,
            "normalizedFrom": "",
            "hint": "",
            "shareSwitchRequired": False,
            "blocked": False,
            "requestedUnc": None,
            "mountSource": get_network_mount_source_for_photo_dir(),
        }

    if re.match(r"^[A-Za-z]:([\\/]|$)", raw):
        return {
            "mappedPath": None,
            "normalizedFrom": raw,
            "hint": "Windows-Laufwerkspfad erkannt. Bitte UNC (\\\\SERVER\\Share\\Ordner) oder Linux-Pfad (/mnt/...) verwenden.",
            "shareSwitchRequired": False,
            "blocked": True,
            "requestedUnc": None,
            "mountSource": get_network_mount_source_for_photo_dir(),
        }

    is_unc = raw.startswith("\\\\") or "\\" in raw or (raw.startswith("//") and not raw.startswith("/mnt/"))
    mount_src = get_network_mount_source_for_photo_dir()

    if is_unc:
        req = parse_unc_path(raw)
        mount_req = parse_unc_path(mount_src) if mount_src.startswith("//") or mount_src.startswith("\\\\") else None

        if req and mount_req:
            same = req["server"].lower() == mount_req["server"].lower() and req["share"].lower() == mount_req["share"].lower()
            if not same:
                return {
                    "mappedPath": None,
                    "normalizedFrom": raw,
                    "hint": f"Anderer Share erkannt ({req['server']}/{req['share']}). Aktueller Linux-Mount ist {mount_req['server']}/{mount_req['share']}. Für Share-Wechsel ist ein Admin-Remount nötig.",
                    "shareSwitchRequired": True,
                    "blocked": True,
                    "requestedUnc": req,
                    "mountSource": mount_src,
                }

            rel_path = "/".join(req.get("subparts") or [])
            mapped = os.path.abspath(os.path.join(PHOTO_DIR, rel_path)) if rel_path else PHOTO_DIR
            return {
                "mappedPath": mapped[:256],
                "normalizedFrom": raw,
                "hint": "UNC erkannt und auf aktiven Linux-Mount abgebildet.",
                "shareSwitchRequired": False,
                "blocked": False,
                "requestedUnc": req,
                "mountSource": mount_src,
            }

        # Fallback ohne eindeutige Mount-Info:
        # bei UNC immer Admin-Share-Wechsel verlangen, damit /etc/fstab korrekt gesetzt wird.
        req_rel = parse_unc_path(raw)
        return {
            "mappedPath": None,
            "normalizedFrom": raw,
            "hint": "UNC erkannt, aber aktuell ist kein aktiver CIFS-Mount bekannt. Bitte 'Netzwerkordner wechseln (Passwort erforderlich)' ausführen.",
            "shareSwitchRequired": True,
            "blocked": True,
            "requestedUnc": req_rel,
            "mountSource": mount_src,
        }

    if raw.startswith("/"):
        return {
            "mappedPath": os.path.abspath(raw)[:256],
            "normalizedFrom": "",
            "hint": "",
            "shareSwitchRequired": False,
            "blocked": False,
            "requestedUnc": None,
            "mountSource": mount_src,
        }

    return {
        "mappedPath": PHOTO_DIR,
        "normalizedFrom": raw,
        "hint": "Ungültiges Format; verwende Linux-Pfad oder UNC.",
        "shareSwitchRequired": False,
        "blocked": False,
        "requestedUnc": None,
        "mountSource": mount_src,
    }


# ─── SMB Network Browser ────────────────────────────────────────────────────

def _smb_run(cmd, timeout=8):
    """Run an SMB CLI command and return (stdout, stderr, returncode)."""
    try:
        env = {**os.environ, "LANG": "C", "LC_ALL": "C"}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", -1
    except Exception as exc:
        return "", str(exc), -1


def smb_discover_hosts(timeout=5):
    """Discover SMB/CIFS hosts on the local network via nmblookup + avahi."""
    hosts = {}  # ip -> display_name

    # Primary: NetBIOS broadcast (fast, ~2s, needs samba-common)
    stdout, _, _ = _smb_run(["nmblookup", "-T", "*"], timeout=timeout)
    for line in stdout.splitlines():
        # With -T: "192.168.50.10  hostname.local" (DNS resolved)
        # Without -T: "192.168.50.10  *<00>"
        m = re.match(r'^(\d+\.\d+\.\d+\.\d+)\s+(\S+)', line.strip())
        if not m:
            continue
        ip, name = m.group(1), m.group(2)
        name = re.sub(r'<[^>]+>', '', name).strip().rstrip('.')
        if ip.endswith('.255') or ip == '0.0.0.0' or not name or name == '*':
            continue
        if ip not in hosts:
            hosts[ip] = name

    # Secondary: mDNS / Bonjour (Linux/Mac NAS with avahi-daemon)
    avahi_bin = None
    for b in ["/usr/bin/avahi-browse", "/usr/local/bin/avahi-browse"]:
        if os.path.isfile(b):
            avahi_bin = b
            break
    if avahi_bin:
        stdout, _, _ = _smb_run([avahi_bin, "-t", "-r", "-p", "_smb._tcp"], timeout=timeout)
        for line in stdout.splitlines():
            if not line.startswith("="):
                continue
            parts = line.split(";")
            if len(parts) >= 8:
                name = parts[3].strip("'\" ")
                ip   = parts[7].strip("'\" ")
                if ip and re.match(r'^\d+\.\d+\.\d+\.\d+$', ip) and ip not in hosts:
                    hosts[ip] = name

    return sorted(
        [{"ip": ip, "name": name} for ip, name in hosts.items()],
        key=lambda h: h["ip"]
    )


def smb_list_shares(host, user="", password="", timeout=8):
    """List Disk-type shares on an SMB host. Returns (shares, ok, err_msg)."""
    if user:
        auth = f"{user}%{password}" if password else user
        cmd = ["smbclient", "-U", auth, "-L", f"//{host}"]
    else:
        cmd = ["smbclient", "-N", "-L", f"//{host}"]

    stdout, stderr, rc = _smb_run(cmd, timeout=timeout)
    shares = []
    in_list = False
    past_sep = False

    for line in stdout.splitlines():
        if "Sharename" in line and "Type" in line:
            in_list = True
            continue
        if not in_list:
            continue
        if re.match(r'^\s*-{3,}', line):
            past_sep = True
            continue
        if not past_sep:
            continue
        stripped = line.strip()
        if not stripped:
            break
        parts = stripped.split()
        if len(parts) < 2:
            continue
        sname  = parts[0]
        stype  = parts[1].upper()
        comment = " ".join(parts[2:]) if len(parts) > 2 else ""
        if sname.upper().endswith("$") or stype in ("IPC", "PRINTER"):
            continue
        shares.append({"name": sname, "type": stype, "comment": comment})

    ok = bool(shares) or "Sharename" in stdout
    return shares, ok, ("" if ok else stderr.strip())


def smb_browse_folder(host, share, path="", user="", password="", timeout=8):
    """List directory entries in an SMB share path. Returns (entries, ok, err_msg)."""
    smb_path = path.replace("/", "\\").strip("\\")
    ls_cmd = f"ls \\{smb_path}\\*" if smb_path else "ls"

    if user:
        auth = f"{user}%{password}" if password else user
        cmd = ["smbclient", f"//{host}/{share}", "-U", auth, "-c", ls_cmd]
    else:
        cmd = ["smbclient", f"//{host}/{share}", "-N", "-c", ls_cmd]

    stdout, stderr, rc = _smb_run(cmd, timeout=timeout)
    entries = []

    for line in stdout.splitlines():
        # "  filename                         D        0  Mon Jan  1 00:00:00 2026"
        # Greedy name match -> nimmt den letzten Attribute/Size-Block, robuster bei Dateinamen mit " D " etc.
        m = re.match(r'^\s+(.+)\s+(D|A|H|N|R|S)\s+(-?\d+)\s+[A-Za-z]{3}\s', line)
        if not m:
            continue
        name = m.group(1).strip()
        is_dir = m.group(2) == "D"
        if name in (".", ".."):
            continue
        entries.append({"name": name, "type": "dir" if is_dir else "file"})

    ok = bool(entries) or rc == 0
    return entries, ok, ("" if ok else stderr.strip())


# ─── end SMB Network Browser ──────────────────────────────────────────────────

def get_storage_diagnostics():
    st = get_storage_state()
    network = st.get("network", {})
    path = network.get("path") or PHOTO_DIR
    mount_source = get_network_mount_source_for_photo_dir()
    mount_ok = bool(mount_source)

    checklist = [
        {"key": "path_exists", "label": "Pfad vorhanden", "ok": bool(network.get("exists"))},
        {"key": "is_mount", "label": "Als Netzwerk-Share gemountet", "ok": bool(mount_ok)},
        {"key": "writable", "label": "Schreibbar", "ok": bool(network.get("writable"))},
    ]

    # Schnellcheck statt echtem Dateischreibtest, damit die Diagnose nie hängt
    write_test = {
        "ok": bool(network.get("exists") and network.get("writable")),
        "message": "Schnellcheck über Schreibrechte",
    }

    checklist.append({"key": "write_test", "label": "Datei anlegen/löschen", "ok": bool(write_test.get("ok"))})

    effective_ok = bool(
        (mount_ok and network.get("writable") and write_test.get("ok"))
        or (st.get("activeSource") == "network" and write_test.get("ok"))
    )

    if effective_ok:
        reason = "Netzwerkordner ist bereit."
        next_action = "Alles gut – du kannst direkt weiterarbeiten."
    elif not network.get("exists"):
        reason = "Netzwerkpfad existiert nicht."
        next_action = "Pfad prüfen oder zuerst Share verbinden."
    elif not mount_ok:
        reason = "Pfad ist nicht als CIFS-Share gemountet."
        next_action = "Button 'Share neu verbinden' oder 'Netzwerkordner wechseln (Passwort erforderlich)' nutzen."
    elif not network.get("writable"):
        reason = "Share ist gemountet, aber nicht schreibbar."
        next_action = "CIFS-Rechte/credentials prüfen und neu verbinden."
    elif not write_test.get("ok"):
        reason = write_test.get("message") or "Schreibtest fehlgeschlagen."
        next_action = "Share-Berechtigungen prüfen."
    else:
        reason = "Netzwerkordner ist bereit."
        next_action = "Du kannst auf 'Netzwerkordner nutzen' umschalten."

    mount_info = ""
    if mount_source:
        mount_info = f"{mount_source} -> {PHOTO_DIR}"

    path_owner = ""
    path_mode = ""
    try:
        st_mode = os.stat(path)
        path_owner = f"uid:{st_mode.st_uid} gid:{st_mode.st_gid}"
        path_mode = oct(st_mode.st_mode & 0o777)
    except Exception:
        pass

    return {
        "ok": effective_ok,
        "reason": reason,
        "nextAction": next_action,
        "activeSource": st.get("activeSource"),
        "checklist": checklist,
        "networkPath": path,
        "mountSource": mount_source,
        "mountInfo": mount_info,
        "pathOwner": path_owner,
        "pathMode": path_mode,
        "mode": st.get("mode"),
        "updatedAt": time.time(),
    }


def get_storage_state():
    storage = sanitize_storage_config((SERVER_CONFIG or {}).get("storage", {}))
    network_path = storage.get("networkPath", PHOTO_DIR)
    local_path = storage.get("localPath", FALLBACK_PHOTO_DIR)
    mode = storage.get("mode", "auto")

    # lokales Ziel immer verfügbar machen
    os.makedirs(local_path, exist_ok=True)

    network_ready = is_writable_dir(network_path)
    local_ready = is_writable_dir(local_path)

    if mode == "network" and network_ready:
        active_path = network_path
        active_source = "network"
    elif mode == "local":
        active_path = local_path
        active_source = "local"
    else:
        if network_ready:
            active_path = network_path
            active_source = "network"
        else:
            active_path = local_path
            active_source = "local"

    return {
        "mode": mode,
        "activePath": active_path,
        "activeSource": active_source,
        "rawNetworkPath": str(storage.get("rawNetworkPath") or network_path),
        "network": {
            "path": network_path,
            "exists": safe_isdir(network_path),
            "mount": bool(get_network_mount_source_for_photo_dir()),
            "writable": network_ready,
        },
        "local": {
            "path": local_path,
            "exists": safe_isdir(local_path),
            "mount": safe_ismount(local_path),
            "writable": local_ready,
        },
        "updatedAt": float(storage.get("updatedAt") or 0.0),
    }


def get_photo_dir():
    return get_storage_state().get("activePath", ensure_local_photo_dir())


def clamp_refresh_ms(value):
    try:
        value = int(value)
    except:
        value = DEFAULT_REFRESH_MS
    if value < MIN_REFRESH_MS:
        value = MIN_REFRESH_MS
    if value > MAX_REFRESH_MS:
        value = MAX_REFRESH_MS
    return value


def clamp_brightness(value):
    try:
        value = int(value)
    except:
        value = 180
    if value < 0:
        value = 0
    if value > 255:
        value = 255
    return value


def normalize_hex_color(value):
    s = str(value or "").strip().upper()
    if re.fullmatch(r"#[0-9A-F]{6}", s):
        return s
    return "#FFD6A0"


def clamp_color_index(value):
    try:
        idx = int(value)
    except:
        idx = 0
    if idx < -1:
        return -1
    if idx >= len(LED_COLORS):
        return -1
    return idx


def clamp_led_order(value):
    s = str(value or "GRB").strip().upper()
    allowed = {"RGB", "GRB", "BRG", "BGR", "RBG", "GBR"}
    return s if s in allowed else "GRB"


def sanitize_led_config(raw):
    raw = raw or {}
    return {
        "on": bool(raw.get("on", True)),
        "brightness": clamp_brightness(raw.get("brightness", 180)),
        "color": normalize_hex_color(raw.get("color", "#FFD6A0")),
        "colorIndex": clamp_color_index(raw.get("colorIndex", 0)),
        "ledOrder": clamp_led_order(raw.get("ledOrder", raw.get("led_order", "GRB"))),
        "source": str(raw.get("source", "server") or "server")[:32],
        "updatedAt": float(raw.get("updatedAt") or 0.0),
    }


def clamp_motor_pulse(value, fallback):
    try:
        v = int(value)
    except Exception:
        v = int(fallback)
    if v < 500:
        v = 500
    if v > 8000:
        v = 8000
    return v


def clamp_motor_delay_ms(value, fallback=600):
    try:
        v = int(value)
    except Exception:
        v = int(fallback)
    if v < 120:
        v = 120
    if v > 5000:
        v = 5000
    return v


def sanitize_motor_config(raw):
    raw = raw or {}
    cmd = str(raw.get("commandOrientation", "") or "").strip().lower()
    if cmd not in ("portrait", "landscape"):
        cmd = ""

    return {
        "enabled": bool(raw.get("enabled", True)),
        "portraitPulse": clamp_motor_pulse(raw.get("portraitPulse", 1638), 1638),
        "landscapePulse": clamp_motor_pulse(raw.get("landscapePulse", 4915), 4915),
        "moveDelayMs": clamp_motor_delay_ms(raw.get("moveDelayMs", 600), 600),
        "commandToken": str(raw.get("commandToken", "") or "")[:64],
        "commandOrientation": cmd,
        "source": str(raw.get("source", "server") or "server")[:32],
        "updatedAt": float(raw.get("updatedAt") or 0.0),
    }


def sanitize_wlan_config(raw):
    raw = raw or {}
    ssid = str(raw.get("ssid", "") or "").strip()[:128]
    password = str(raw.get("password", "") or "")[:128]
    esp_host = str(raw.get("espHost", "") or "").strip()[:128]
    server_base = str(raw.get("serverBase", "http://frame-server.local:8765") or "").strip()[:256]
    fallback_enabled = bool(raw.get("fallbackEnabled", False))
    fallback_server_base = str(raw.get("fallbackServerBase", "") or "").strip()[:256]
    try:
        sync_timeout_ms = int(raw.get("syncTimeoutMs", 1500))
    except Exception:
        sync_timeout_ms = 1500
    if sync_timeout_ms < 600:
        sync_timeout_ms = 600
    if sync_timeout_ms > 5000:
        sync_timeout_ms = 5000
    return {
        "ssid": ssid,
        "password": password,
        "espHost": esp_host,
        "serverBase": server_base,
        "fallbackEnabled": fallback_enabled,
        "fallbackServerBase": fallback_server_base,
        "syncTimeoutMs": sync_timeout_ms,
        "updatedAt": float(raw.get("updatedAt") or 0.0),
    }


def sanitize_esp_sync(raw):
    raw = raw or {}
    return {
        "desiredToken": str(raw.get("desiredToken", "") or "")[:64],
        "lastPrepareAt": float(raw.get("lastPrepareAt") or 0.0),
        "lastAckToken": str(raw.get("lastAckToken", "") or "")[:64],
        "lastAckAt": float(raw.get("lastAckAt") or 0.0),
        "lastAckIp": str(raw.get("lastAckIp", "") or "")[:64],
    }


def sanitize_storage_auth(raw):
    raw = raw or {}
    username = str(raw.get("username", "") or "").strip()[:128]
    password = str(raw.get("password", "") or "")[:128]
    return {
        "username": username,
        "password": password,
        "updatedAt": float(raw.get("updatedAt") or 0.0),
    }


def load_config():
    cfg = {
        "refreshMs": DEFAULT_REFRESH_MS,
        "led": sanitize_led_config({}),
        "motor": sanitize_motor_config({}),
        "wlan": sanitize_wlan_config({}),
        "espSync": sanitize_esp_sync({}),
        "storage": sanitize_storage_config({}),
        "storageAuth": sanitize_storage_auth({}),
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            disk = json.load(f)
            cfg["refreshMs"] = clamp_refresh_ms(disk.get("refreshMs", DEFAULT_REFRESH_MS))
            cfg["led"] = sanitize_led_config(disk.get("led", {}))
            cfg["motor"] = sanitize_motor_config(disk.get("motor", {}))
            cfg["wlan"] = sanitize_wlan_config(disk.get("wlan", {}))
            cfg["espSync"] = sanitize_esp_sync(disk.get("espSync", {}))
            cfg["storage"] = sanitize_storage_config(disk.get("storage", {}))
            cfg["storageAuth"] = sanitize_storage_auth(disk.get("storageAuth", {}))
    except:
        pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    payload = {
        "refreshMs": clamp_refresh_ms(cfg.get("refreshMs", DEFAULT_REFRESH_MS)),
        "led": sanitize_led_config(cfg.get("led", {})),
        "motor": sanitize_motor_config(cfg.get("motor", {})),
        "wlan": sanitize_wlan_config(cfg.get("wlan", {})),
        "espSync": sanitize_esp_sync(cfg.get("espSync", {})),
        "storage": sanitize_storage_config(cfg.get("storage", {})),
        "storageAuth": sanitize_storage_auth(cfg.get("storageAuth", {})),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def sanitize_filename(name: str) -> str:
    name = os.path.basename((name or "").strip())
    if not name:
        return ""
    name = name.replace("\x00", "")
    name = re.sub(r"[^A-Za-z0-9._\- ()]", "_", name)
    return name[:180]


def update_upload_status(**kwargs):
    with UPLOAD_LOCK:
        UPLOAD_STATUS.update(kwargs)
        UPLOAD_STATUS["updatedAt"] = time.time()


def get_upload_status_snapshot():
    with UPLOAD_LOCK:
        snap = dict(UPLOAD_STATUS)
    age = time.time() - float(snap.get("updatedAt") or 0)
    show = bool(snap.get("active")) or (
        snap.get("phase") in ("done", "error") and age < 6
    )
    snap["show"] = show
    return snap


def update_frame_state(filename="", orientation="", index=-1, count=0, source=""):
    with FRAME_STATE_LOCK:
        FRAME_STATE["filename"] = filename or ""
        FRAME_STATE["orientation"] = orientation or ""
        FRAME_STATE["index"] = int(index) if str(index).strip() != "" else -1
        FRAME_STATE["count"] = int(count) if str(count).strip() != "" else 0
        FRAME_STATE["updatedAt"] = time.time()
        FRAME_STATE["source"] = source or ""
        photo_root = os.path.abspath(get_photo_dir())
        if filename:
            candidate = os.path.abspath(os.path.join(photo_root, filename))
            FRAME_STATE["exists"] = candidate.startswith(photo_root + os.sep) and os.path.isfile(candidate)
        else:
            FRAME_STATE["exists"] = False


def get_frame_state_snapshot():
    with FRAME_STATE_LOCK:
        snap = dict(FRAME_STATE)
    return snap


def get_led_config_snapshot():
    with LED_LOCK:
        led = sanitize_led_config((SERVER_CONFIG or {}).get("led", {}))
        led["catalog"] = LED_COLORS
        return led


def get_motor_config_snapshot():
    return sanitize_motor_config((SERVER_CONFIG or {}).get("motor", {}))


def update_motor_config(patch: dict):
    with CONFIG_LOCK:
        current = sanitize_motor_config((SERVER_CONFIG or {}).get("motor", {}))

        if "enabled" in patch:
            current["enabled"] = bool(patch.get("enabled"))
        if "portraitPulse" in patch:
            current["portraitPulse"] = clamp_motor_pulse(patch.get("portraitPulse"), current.get("portraitPulse", 1638))
        if "landscapePulse" in patch:
            current["landscapePulse"] = clamp_motor_pulse(patch.get("landscapePulse"), current.get("landscapePulse", 4915))
        if "moveDelayMs" in patch:
            current["moveDelayMs"] = clamp_motor_delay_ms(patch.get("moveDelayMs"), current.get("moveDelayMs", 600))

        test_orientation = str(patch.get("testOrientation", "") or "").strip().lower()
        if test_orientation in ("portrait", "landscape"):
            current["commandOrientation"] = test_orientation
            current["commandToken"] = str(int(time.time() * 1000))

        if bool(patch.get("clearCommand")):
            current["commandOrientation"] = ""
            current["commandToken"] = ""

        if "source" in patch:
            current["source"] = str(patch.get("source") or "server")[:32]

        current["updatedAt"] = time.time()
        SERVER_CONFIG["motor"] = current
        save_config(SERVER_CONFIG)
        return dict(current)


def update_led_config(patch: dict):
    with LED_LOCK:
        with CONFIG_LOCK:
            current = sanitize_led_config((SERVER_CONFIG or {}).get("led", {}))
            if "on" in patch:
                current["on"] = bool(patch.get("on"))
            if "brightness" in patch:
                current["brightness"] = clamp_brightness(patch.get("brightness"))
            if "color" in patch:
                current["color"] = normalize_hex_color(patch.get("color"))
            if "colorIndex" in patch:
                current["colorIndex"] = clamp_color_index(patch.get("colorIndex"))
            if "ledOrder" in patch or "led_order" in patch:
                current["ledOrder"] = clamp_led_order(patch.get("ledOrder", patch.get("led_order")))
            if "source" in patch:
                current["source"] = str(patch.get("source") or "server")[:32]
            current["updatedAt"] = time.time()

            SERVER_CONFIG["led"] = current
            save_config(SERVER_CONFIG)

            out = dict(current)
            out["catalog"] = LED_COLORS
            return out


def get_wlan_config_snapshot(mask_password=False):
    wlan = sanitize_wlan_config((SERVER_CONFIG or {}).get("wlan", {}))
    if mask_password and wlan.get("password"):
        wlan["password"] = "********"
    return wlan


def update_wlan_config(patch: dict):
    with CONFIG_LOCK:
        current = sanitize_wlan_config((SERVER_CONFIG or {}).get("wlan", {}))
        if "ssid" in patch:
            current["ssid"] = str(patch.get("ssid") or "").strip()[:128]
        if "password" in patch:
            current["password"] = str(patch.get("password") or "")[:128]
        if "espHost" in patch:
            current["espHost"] = str(patch.get("espHost") or "").strip()[:128]
        if "serverBase" in patch:
            current["serverBase"] = str(patch.get("serverBase") or "").strip()[:256]
        if "fallbackEnabled" in patch:
            current["fallbackEnabled"] = bool(patch.get("fallbackEnabled"))
        if "fallbackServerBase" in patch:
            current["fallbackServerBase"] = str(patch.get("fallbackServerBase") or "").strip()[:256]
        if "syncTimeoutMs" in patch:
            try:
                tm = int(patch.get("syncTimeoutMs"))
            except Exception:
                tm = current.get("syncTimeoutMs", 1500)
            if tm < 600:
                tm = 600
            if tm > 5000:
                tm = 5000
            current["syncTimeoutMs"] = tm
        current["updatedAt"] = time.time()
        SERVER_CONFIG["wlan"] = current
        save_config(SERVER_CONFIG)
        return dict(current)


def get_esp_sync_snapshot():
    return sanitize_esp_sync((SERVER_CONFIG or {}).get("espSync", {}))


def mark_esp_prepare_requested():
    with CONFIG_LOCK:
        sync = sanitize_esp_sync((SERVER_CONFIG or {}).get("espSync", {}))
        token = str(int(time.time() * 1000))
        sync["desiredToken"] = token
        sync["lastPrepareAt"] = time.time()
        SERVER_CONFIG["espSync"] = sync
        save_config(SERVER_CONFIG)
        return dict(sync)


def mark_esp_wlan_pull(client_ip=""):
    with CONFIG_LOCK:
        sync = sanitize_esp_sync((SERVER_CONFIG or {}).get("espSync", {}))
        sync["lastAckAt"] = time.time()
        if client_ip:
            sync["lastAckIp"] = str(client_ip)[:64]
        desired = str(sync.get("desiredToken") or "")
        if desired:
            sync["lastAckToken"] = desired
        SERVER_CONFIG["espSync"] = sync
        save_config(SERVER_CONFIG)
        return dict(sync)


def get_esp_sync_status():
    wlan = sanitize_wlan_config((SERVER_CONFIG or {}).get("wlan", {}))
    sync = sanitize_esp_sync((SERVER_CONFIG or {}).get("espSync", {}))
    desired = str(sync.get("desiredToken") or "")
    ack = str(sync.get("lastAckToken") or "")
    prepare_at = float(sync.get("lastPrepareAt") or 0.0)
    ack_at = float(sync.get("lastAckAt") or 0.0)
    now = time.time()

    is_synced = bool(desired) and desired == ack and ack_at >= prepare_at
    seconds_since_ack = int(max(0.0, now - ack_at)) if ack_at > 0 else None

    return {
        "desiredToken": desired,
        "lastAckToken": ack,
        "lastPrepareAt": prepare_at,
        "lastAckAt": ack_at,
        "lastAckIp": sync.get("lastAckIp", ""),
        "isSynced": is_synced,
        "secondsSinceAck": seconds_since_ack,
        "espHost": wlan.get("espHost", ""),
    }


def get_storage_auth_snapshot(mask_password=True):
    auth = sanitize_storage_auth((SERVER_CONFIG or {}).get("storageAuth", {}))
    if mask_password:
        out = {
            "username": auth.get("username", ""),
            "hasPassword": bool(auth.get("password")),
            "updatedAt": auth.get("updatedAt", 0.0),
        }
        return out
    return dict(auth)


def update_storage_auth(patch: dict):
    with CONFIG_LOCK:
        current = sanitize_storage_auth((SERVER_CONFIG or {}).get("storageAuth", {}))
        if "username" in patch:
            current["username"] = str(patch.get("username") or "").strip()[:128]
        if "password" in patch:
            current["password"] = str(patch.get("password") or "")[:128]
        current["updatedAt"] = time.time()
        SERVER_CONFIG["storageAuth"] = current
        save_config(SERVER_CONFIG)
    return get_storage_auth_snapshot(mask_password=True)


def get_storage_config_snapshot():
    return get_storage_state()


def update_storage_config(patch: dict):
    normalized_from = ""
    normalized_hint = ""
    share_switch_required = False
    blocked = False

    with CONFIG_LOCK:
        current = sanitize_storage_config((SERVER_CONFIG or {}).get("storage", {}))
        requested_mode = None
        if "mode" in patch:
            mode = str(patch.get("mode") or "auto").strip().lower()
            if mode in ("auto", "local", "network"):
                requested_mode = mode
        if "networkPath" in patch:
            current["rawNetworkPath"] = str(patch.get("networkPath") or "").strip()[:256]
            analysis = analyze_network_path_input(patch.get("networkPath"))
            normalized_from = analysis.get("normalizedFrom", "")
            normalized_hint = analysis.get("hint", "")
            share_switch_required = bool(analysis.get("shareSwitchRequired"))
            blocked = bool(analysis.get("blocked"))
            path = analysis.get("mappedPath")
            if path:
                current["networkPath"] = path
        if requested_mode:
            # Netzwerkmodus nur setzen, wenn Eingabe nicht geblockt wurde
            if not (requested_mode == "network" and blocked):
                current["mode"] = requested_mode
        if "localPath" in patch:
            path = str(patch.get("localPath") or "").strip()
            if path.startswith("/"):
                current["localPath"] = os.path.abspath(path)[:256]

        current["updatedAt"] = time.time()
        SERVER_CONFIG["storage"] = current
        save_config(SERVER_CONFIG)
    out = get_storage_state()
    out["normalizedNetworkPathFrom"] = normalized_from
    out["normalizedNetworkPathHint"] = normalized_hint
    out["shareSwitchRequired"] = share_switch_required
    out["blocked"] = blocked
    return out


def test_esp_host(host, port=80, timeout_seconds=1.5):
    host = str(host or "").strip()
    if not host:
        return {"ok": False, "error": "espHost fehlt"}

    # 1) ICMP Ping als Basis-Erreichbarkeit
    try:
        ping = subprocess.run(
            ["ping", "-c", "1", "-W", "1", host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if ping.returncode == 0:
            return {"ok": True, "mode": "ping", "message": "ESP erreichbar (Ping)"}
    except Exception:
        pass

    # 2) Fallback TCP-Test
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            return {"ok": True, "mode": "tcp", "message": f"ESP Port {int(port)} erreichbar"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _read_local_share_credentials_file():
    user = ""
    pw = ""
    for creds_path in (LOCAL_SHARE_CREDENTIALS_PATH, '/etc/samba/.muffi-credentials'):
        if not creds_path:
            continue
        try:
            with open(creds_path, 'r', encoding='utf-8', errors='ignore') as cf:
                for line in cf:
                    line = line.strip()
                    if line.startswith('username=') and not user:
                        user = line.split('=', 1)[1].strip()[:128]
                    elif line.startswith('password=') and not pw:
                        pw = line.split('=', 1)[1].strip()[:128]
            if user and pw:
                break
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return user, pw


def resolve_share_credentials(share_user: str = "", share_password: str = ""):
    smb_user = str(share_user or "").strip()[:128]
    smb_pass = str(share_password or "").strip()[:128]

    # 1) explizite Eingabe gewinnt
    if smb_user and smb_pass:
        return smb_user, smb_pass

    # 2) lokale Credentials-Datei
    file_user, file_pass = _read_local_share_credentials_file()
    if not smb_user:
        smb_user = file_user
    if not smb_pass:
        smb_pass = file_pass
    if smb_user and smb_pass:
        return smb_user, smb_pass

    # 3) gespeicherte UI-Auth in Config
    saved = sanitize_storage_auth((SERVER_CONFIG or {}).get("storageAuth", {}))
    if not smb_user:
        smb_user = saved.get("username", "")
    if not smb_pass:
        smb_pass = saved.get("password", "")

    return smb_user, smb_pass


def test_share_credentials(username: str, password: str, network_path: str = ""):
    user = str(username or "").strip()
    pw = str(password or "")
    if not user or not pw:
        return {"ok": False, "error": "Benutzer oder Passwort fehlt"}

    host = ""
    share = ""
    req = parse_unc_path(network_path)
    if req:
        host = req.get("server", "")
        share = req.get("share", "")

    if not host or not share:
        mount_src = get_network_mount_source_for_photo_dir()
        req2 = parse_unc_path(mount_src) if mount_src else None
        if req2:
            host = host or req2.get("server", "")
            share = share or req2.get("share", "")

    if not host or not share:
        return {"ok": False, "error": "Kein aktiver CIFS-Mount gefunden. Bitte erst Share verbinden."}

    cmd = ["smbclient", f"//{host}/{share}", "-U", f"{user}%{pw}", "-c", "ls"]
    _out, err, rc = _smb_run(cmd, timeout=8)
    if rc == 0:
        return {"ok": True, "host": host, "share": share, "message": "SMB Zugang erfolgreich getestet"}
    return {"ok": False, "host": host, "share": share, "error": (err or "SMB Zugriff fehlgeschlagen")[:300]}


def _update_append_line(line: str):
    text = str(line or "").rstrip("\n")
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    with UPDATE_LOCK:
        UPDATE_STATE["lines"].append(text)
        # Speicher begrenzen
        if len(UPDATE_STATE["lines"]) > 1500:
            UPDATE_STATE["lines"] = UPDATE_STATE["lines"][-1500:]


def _resolve_update_script_path():
    candidates = [
        os.path.abspath(os.path.join(RUNTIME_DIR, "..", "install", "linux", "update-muffi-frame.sh")),
        os.path.abspath(os.path.join(RUNTIME_DIR, "..", "..", "install", "linux", "update-muffi-frame.sh")),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return ""


def _resolve_esp_update_script_path():
    env_path = os.environ.get("MUFFI_ESP_UPDATE_SCRIPT", "").strip()
    if env_path:
        p = os.path.abspath(env_path)
        if os.path.isfile(p):
            return p

    candidates = [
        os.path.join(RUNTIME_DIR, "..", "install", "linux", "update-esp-ota.sh"),
        os.path.join(RUNTIME_DIR, "..", "scripts", "update-esp-ota.sh"),
    ]
    for c in candidates:
        p = os.path.abspath(c)
        if os.path.isfile(p):
            return p
    return ""


def start_update_job():
    script = _resolve_update_script_path()
    if not script:
        return {"ok": False, "error": "Update-Skript nicht gefunden (install/linux/update-muffi-frame.sh)"}

    script_to_run = script
    tmp_script = ""
    remote_url = os.environ.get(
        "MUFFI_UPDATE_SCRIPT_URL",
        "https://raw.githubusercontent.com/Onkels-Bastelbude/Muffi-Desktop-Rhamen/main/install/linux/update-muffi-frame.sh",
    )

    # Best effort: immer zuerst neuestes Update-Skript von GitHub holen.
    try:
        with tempfile.NamedTemporaryFile(prefix="muffi-update-", suffix=".sh", delete=False) as tf:
            tmp_script = tf.name
        dl = subprocess.run(
            ["curl", "-fsSL", remote_url, "-o", tmp_script],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if dl.returncode == 0 and os.path.getsize(tmp_script) > 0:
            try:
                os.chmod(tmp_script, 0o700)
            except Exception:
                pass
            script_to_run = tmp_script
        else:
            if tmp_script and os.path.exists(tmp_script):
                try:
                    os.unlink(tmp_script)
                except Exception:
                    pass
            tmp_script = ""
    except Exception:
        if tmp_script and os.path.exists(tmp_script):
            try:
                os.unlink(tmp_script)
            except Exception:
                pass
        tmp_script = ""

    with UPDATE_LOCK:
        if UPDATE_STATE.get("phase") == "running":
            return {"ok": False, "error": "Update läuft bereits"}
        UPDATE_STATE.update({
            "phase": "running",
            "lines": [],
            "exitCode": None,
            "startedAt": time.time(),
            "finishedAt": 0.0,
            "scriptPath": script_to_run,
        })

    def _runner():
        _update_append_line(f"[info] starte: {script_to_run}")
        try:
            install_dir = os.environ.get("MUFFI_INSTALL_DIR") or os.path.abspath(os.path.join(RUNTIME_DIR, ".."))
            old_rev = ""

            def _rev_label(rev: str) -> str:
                if not rev:
                    return "unknown"
                try:
                    dt = subprocess.run(
                        ["git", "-C", install_dir, "show", "-s", "--format=%cd", "--date=format-local:%Y%m%d-%H%M", rev],
                        capture_output=True,
                        text=True,
                        timeout=4,
                        check=False,
                    )
                    if dt.returncode == 0 and (dt.stdout or "").strip():
                        return (dt.stdout or "").strip()
                except Exception:
                    pass
                return "unknown"

            try:
                gr = subprocess.run(
                    ["git", "-C", install_dir, "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
                if gr.returncode == 0:
                    old_rev = (gr.stdout or "").strip()
            except Exception:
                pass

            proc = subprocess.Popen(
                ["bash", script_to_run],
                cwd=os.path.dirname(script),
                env={
                    **os.environ,
                    "SKIP_SERVICE_RESTART": "1",
                    "INSTALL_DIR": install_dir,
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            if proc.stdout is not None:
                for line in proc.stdout:
                    _update_append_line(line)

            proc.wait()
            with UPDATE_LOCK:
                UPDATE_STATE["exitCode"] = int(proc.returncode)
                UPDATE_STATE["phase"] = "done" if proc.returncode == 0 else "error"
                UPDATE_STATE["finishedAt"] = time.time()

            if proc.returncode == 0:
                new_rev = ""
                try:
                    gr2 = subprocess.run(
                        ["git", "-C", install_dir, "rev-parse", "--short", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=4,
                        check=False,
                    )
                    if gr2.returncode == 0:
                        new_rev = (gr2.stdout or "").strip()
                except Exception:
                    pass

                if old_rev and new_rev and old_rev == new_rev:
                    _update_append_line(f"[info] Version ist aktuell ({_rev_label(new_rev)})")
                elif new_rev:
                    old_v = _rev_label(old_rev) if old_rev else "none"
                    new_v = _rev_label(new_rev)
                    _update_append_line(f"[info] Update angewendet: {old_v} -> {new_v}")

            if tmp_script and os.path.exists(tmp_script):
                try:
                    os.unlink(tmp_script)
                except Exception:
                    pass
        except Exception as e:
            _update_append_line(f"[error] exception: {e}")
            with UPDATE_LOCK:
                UPDATE_STATE["exitCode"] = -1
                UPDATE_STATE["phase"] = "error"
                UPDATE_STATE["finishedAt"] = time.time()
            if tmp_script and os.path.exists(tmp_script):
                try:
                    os.unlink(tmp_script)
                except Exception:
                    pass

    threading.Thread(target=_runner, daemon=True).start()
    return {"ok": True, "message": "Update gestartet"}


def get_update_status(offset=0):
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    if offset < 0:
        offset = 0

    with UPDATE_LOCK:
        lines = UPDATE_STATE.get("lines", [])
        total = len(lines)
        if offset > total:
            offset = total
        return {
            "phase": UPDATE_STATE.get("phase", "idle"),
            "exitCode": UPDATE_STATE.get("exitCode"),
            "startedAt": float(UPDATE_STATE.get("startedAt") or 0.0),
            "finishedAt": float(UPDATE_STATE.get("finishedAt") or 0.0),
            "scriptPath": UPDATE_STATE.get("scriptPath", ""),
            "offset": offset,
            "totalLines": total,
            "lines": lines[offset:],
        }


def _esp_update_append_line(line):
    text = str(line or "").rstrip("\n")
    if not text:
        return
    with ESP_UPDATE_LOCK:
        ESP_UPDATE_STATE["lines"].append(text)
        if len(ESP_UPDATE_STATE["lines"]) > 1500:
            ESP_UPDATE_STATE["lines"] = ESP_UPDATE_STATE["lines"][-1500:]


def start_esp_update_job(esp_host=""):
    host = str(esp_host or "").strip()
    if not host:
        host = get_wlan_config_snapshot(mask_password=False).get("espHost", "")
    host = str(host or "").strip()
    if not host:
        return {"ok": False, "error": "ESP Host fehlt"}

    script = _resolve_esp_update_script_path()
    if not script:
        return {"ok": False, "error": "ESP-Update-Skript nicht gefunden (install/linux/update-esp-ota.sh)"}

    with ESP_UPDATE_LOCK:
        if ESP_UPDATE_STATE.get("phase") == "running":
            return {"ok": False, "error": "ESP-Update läuft bereits"}
        ESP_UPDATE_STATE.update({
            "phase": "running",
            "lines": [],
            "exitCode": None,
            "startedAt": time.time(),
            "finishedAt": 0.0,
            "scriptPath": script,
            "espHost": host,
        })

    def _runner():
        _esp_update_append_line(f"[info] starte OTA für {host}")
        _esp_update_append_line(f"[info] script: {script}")
        try:
            install_dir = os.environ.get("MUFFI_INSTALL_DIR") or os.path.abspath(os.path.join(RUNTIME_DIR, ".."))
            proc = subprocess.Popen(
                ["bash", script],
                cwd=os.path.dirname(script),
                env={
                    **os.environ,
                    "INSTALL_DIR": install_dir,
                    "ESP_HOST": host,
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            if proc.stdout is not None:
                for line in proc.stdout:
                    _esp_update_append_line(line)

            proc.wait()
            with ESP_UPDATE_LOCK:
                ESP_UPDATE_STATE["exitCode"] = int(proc.returncode)
                ESP_UPDATE_STATE["phase"] = "done" if proc.returncode == 0 else "error"
                ESP_UPDATE_STATE["finishedAt"] = time.time()

        except Exception as e:
            _esp_update_append_line(f"[error] exception: {e}")
            with ESP_UPDATE_LOCK:
                ESP_UPDATE_STATE["exitCode"] = -1
                ESP_UPDATE_STATE["phase"] = "error"
                ESP_UPDATE_STATE["finishedAt"] = time.time()

    threading.Thread(target=_runner, daemon=True).start()
    return {"ok": True, "message": f"ESP-Update gestartet ({host})", "espHost": host}


def get_esp_update_status(offset=0):
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    if offset < 0:
        offset = 0

    with ESP_UPDATE_LOCK:
        lines = ESP_UPDATE_STATE.get("lines", [])
        total = len(lines)
        if offset > total:
            offset = total
        return {
            "phase": ESP_UPDATE_STATE.get("phase", "idle"),
            "exitCode": ESP_UPDATE_STATE.get("exitCode"),
            "startedAt": float(ESP_UPDATE_STATE.get("startedAt") or 0.0),
            "finishedAt": float(ESP_UPDATE_STATE.get("finishedAt") or 0.0),
            "scriptPath": ESP_UPDATE_STATE.get("scriptPath", ""),
            "espHost": ESP_UPDATE_STATE.get("espHost", ""),
            "offset": offset,
            "totalLines": total,
            "lines": lines[offset:],
        }


def _resolve_usb_flash_script_path():
    env_path = os.environ.get("MUFFI_ESP_USB_FLASH_SCRIPT", "").strip()
    if env_path:
        p = os.path.abspath(env_path)
        if os.path.isfile(p):
            return p

    candidates = [
        os.path.join(RUNTIME_DIR, "..", "install", "linux", "flash-esp-usb.sh"),
        os.path.join(RUNTIME_DIR, "..", "scripts", "flash-esp-usb.sh"),
    ]
    for c in candidates:
        p = os.path.abspath(c)
        if os.path.isfile(p):
            return p
    return ""


def _resolve_arduino_cli_path():
    env_cli = str(os.environ.get("ARDUINO_CLI", "") or "").strip()
    if env_cli and os.path.isfile(env_cli) and os.access(env_cli, os.X_OK):
        return env_cli

    which_cli = shutil.which("arduino-cli")
    if which_cli:
        return which_cli

    candidates = [
        os.path.expanduser("~/.local/bin/arduino-cli"),
        "/usr/local/bin/arduino-cli",
        "/usr/bin/arduino-cli",
        os.path.abspath(os.path.join(RUNTIME_DIR, "..", "bin", "arduino-cli")),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""


def _list_arduino_ports():
    cli = _resolve_arduino_cli_path()
    if not cli:
        return [], "arduino-cli nicht gefunden"

    try:
        r = subprocess.run(
            [cli, "board", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "Fehler bei arduino-cli board list").strip()
            return [], msg[:300]
        data = json.loads(r.stdout or "{}")
        out = []
        for item in (data.get("detected_ports") or []):
            port = item.get("port") or {}
            address = str(port.get("address") or "").strip()
            if not address:
                continue
            label = str(port.get("label") or "").strip()
            proto = str(port.get("protocol") or "").strip()
            boards = item.get("matching_boards") or []
            names = [str(b.get("name") or "").strip() for b in boards if isinstance(b, dict)]
            fqbn = ""
            for b in boards:
                if isinstance(b, dict) and b.get("fqbn"):
                    fqbn = str(b.get("fqbn"))
                    break
            out.append({
                "address": address,
                "label": label,
                "protocol": proto,
                "boards": names,
                "fqbn": fqbn,
            })
        return out, ""
    except Exception as e:
        return [], str(e)


def get_esp_usb_status():
    ports, error = _list_arduino_ports()
    selected = ""
    for p in ports:
        hay = " ".join([p.get("fqbn", "")] + (p.get("boards") or [])).lower()
        if "esp32c6" in hay or "esp32-c6" in hay:
            selected = p.get("address", "")
            break
    if not selected and ports:
        selected = ports[0].get("address", "")

    return {
        "ports": ports,
        "selectedPort": selected,
        "hasPorts": bool(ports),
        "error": error,
        "arduinoCli": _resolve_arduino_cli_path(),
    }


def check_esp_boot_mode(port: str):
    p = str(port or "").strip()
    if not p:
        return {"ok": False, "error": "Port fehlt"}

    esptool_bin = ""
    try:
        cand = subprocess.run(
            ["sh", "-lc", "ls -1d $HOME/.arduino15/packages/esp32/tools/esptool_py/*/esptool 2>/dev/null | sort -V | tail -n 1"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        esptool_bin = (cand.stdout or "").strip()
    except Exception:
        esptool_bin = ""

    cmd = [esptool_bin, "--chip", "esp32c6", "--port", p, "chip_id"] if esptool_bin else ["python3", "-m", "esptool", "--chip", "esp32c6", "--port", p, "chip_id"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=12, check=False)
        combined = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if r.returncode == 0:
            return {"ok": True, "message": "ESP antwortet auf dem Port (Boot/Auto-Reset ok)", "details": combined[-1200:]}
        return {"ok": False, "error": "Kein Bootloader-Zugriff", "details": combined[-1200:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _esp_usb_flash_append_line(line):
    text = str(line or "").rstrip("\n")
    if not text:
        return
    with ESP_USB_FLASH_LOCK:
        ESP_USB_FLASH_STATE["lines"].append(text)
        if len(ESP_USB_FLASH_STATE["lines"]) > 1500:
            ESP_USB_FLASH_STATE["lines"] = ESP_USB_FLASH_STATE["lines"][-1500:]


def start_esp_usb_flash_job(port: str):
    p = str(port or "").strip()
    if not p:
        return {"ok": False, "error": "Port fehlt"}

    script = _resolve_usb_flash_script_path()
    if not script:
        return {"ok": False, "error": "USB-Flash-Skript nicht gefunden (install/linux/flash-esp-usb.sh)"}

    with ESP_USB_FLASH_LOCK:
        if ESP_USB_FLASH_STATE.get("phase") == "running":
            return {"ok": False, "error": "USB-Flash läuft bereits"}
        ESP_USB_FLASH_STATE.update({
            "phase": "running",
            "lines": [],
            "exitCode": None,
            "startedAt": time.time(),
            "finishedAt": 0.0,
            "scriptPath": script,
            "port": p,
        })

    def _runner():
        _esp_usb_flash_append_line(f"[info] starte USB-Flash auf {p}")
        _esp_usb_flash_append_line(f"[info] script: {script}")
        try:
            install_dir = os.environ.get("MUFFI_INSTALL_DIR") or os.path.abspath(os.path.join(RUNTIME_DIR, ".."))
            proc = subprocess.Popen(
                ["bash", script],
                cwd=os.path.dirname(script),
                env={
                    **os.environ,
                    "INSTALL_DIR": install_dir,
                    "ESP_PORT": p,
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            if proc.stdout is not None:
                for line in proc.stdout:
                    _esp_usb_flash_append_line(line)

            proc.wait()
            with ESP_USB_FLASH_LOCK:
                ESP_USB_FLASH_STATE["exitCode"] = int(proc.returncode)
                ESP_USB_FLASH_STATE["phase"] = "done" if proc.returncode == 0 else "error"
                ESP_USB_FLASH_STATE["finishedAt"] = time.time()
        except Exception as e:
            _esp_usb_flash_append_line(f"[error] exception: {e}")
            with ESP_USB_FLASH_LOCK:
                ESP_USB_FLASH_STATE["exitCode"] = -1
                ESP_USB_FLASH_STATE["phase"] = "error"
                ESP_USB_FLASH_STATE["finishedAt"] = time.time()

    threading.Thread(target=_runner, daemon=True).start()
    return {"ok": True, "message": f"USB-Flash gestartet ({p})", "port": p}


def get_esp_usb_flash_status(offset=0):
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    if offset < 0:
        offset = 0

    with ESP_USB_FLASH_LOCK:
        lines = ESP_USB_FLASH_STATE.get("lines", [])
        total = len(lines)
        if offset > total:
            offset = total
        return {
            "phase": ESP_USB_FLASH_STATE.get("phase", "idle"),
            "exitCode": ESP_USB_FLASH_STATE.get("exitCode"),
            "startedAt": float(ESP_USB_FLASH_STATE.get("startedAt") or 0.0),
            "finishedAt": float(ESP_USB_FLASH_STATE.get("finishedAt") or 0.0),
            "scriptPath": ESP_USB_FLASH_STATE.get("scriptPath", ""),
            "port": ESP_USB_FLASH_STATE.get("port", ""),
            "offset": offset,
            "totalLines": total,
            "lines": lines[offset:],
        }


def trigger_server_restart(delay_seconds=1.0):
    try:
        delay = float(delay_seconds)
    except Exception:
        delay = 1.0
    if delay < 0.2:
        delay = 0.2

    service = os.environ.get("MUFFI_SERVICE_NAME", "frame-server.service")
    cmd = f"sleep {delay}; systemctl --user restart {service}"
    try:
        subprocess.Popen(
            ["sh", "-lc", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True, "message": f"Restart für {service} ausgelöst"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def remount_network_share(password: str, share_user: str = "", share_password: str = ""):
    pw = str(password or "")
    if not pw:
        return {"ok": False, "error": "Passwort fehlt"}

    smb_user, smb_pass = resolve_share_credentials(share_user, share_password)
    if not smb_user or not smb_pass:
        return {"ok": False, "error": "Share-Zugangsdaten fehlen (Benutzer/Passwort)"}

    cred_script = (
        "mkdir -p /etc/samba; "
        "cat > /etc/samba/.muffi-credentials <<'CRED'\n"
        f"username={smb_user}\n"
        f"password={smb_pass}\n"
        "CRED\n"
        "chmod 600 /etc/samba/.muffi-credentials; "
    )

    cmd = [
        "sudo", "-S", "-p", "",
        "sh", "-lc",
        cred_script +
        "systemctl reset-failed mnt-muffi.mount mnt-muffi.automount >/dev/null 2>&1 || true; "
        "umount /mnt/muffi >/dev/null 2>&1 || true; "
        "mount /mnt/muffi",
    ]

    try:
        proc = subprocess.run(
            cmd,
            input=pw + "\n",
            text=True,
            capture_output=True,
            timeout=25,
            check=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "Remount fehlgeschlagen").strip()
        return {"ok": False, "error": msg[:300]}

    update_storage_auth({"username": smb_user, "password": smb_pass})
    return {"ok": True, "message": "Share neu verbunden"}


def switch_network_share(password: str, network_path_value, share_user: str = "", share_password: str = ""):
    pw = str(password or "")
    if not pw:
        return {"ok": False, "error": "Passwort fehlt"}

    req = parse_unc_path(network_path_value)
    if not req:
        return {"ok": False, "error": "Bitte einen UNC-Pfad angeben (z. B. \\\\SERVER\\Share\\Ordner)"}

    target_source = f"//{req['server']}/{req['share']}"
    target_source_fstab = target_source.replace(" ", "\\040")

    smb_user, smb_pass = resolve_share_credentials(share_user, share_password)

    if not smb_user or not smb_pass:
        return {"ok": False, "error": "Share-Zugangsdaten fehlen (username/password)"}

    fstab_script = r'''
import sys, os, shutil, datetime

target = sys.argv[1]
cred_user = sys.argv[2]
cred_pass = sys.argv[3]
path = '/etc/fstab'
cred_file = '/etc/samba/.muffi-credentials'

os.makedirs('/etc/samba', exist_ok=True)
with open(cred_file, 'w', encoding='utf-8') as cf:
    cf.write(f"username={cred_user}\n")
    cf.write(f"password={cred_pass}\n")
os.chmod(cred_file, 0o600)

os.makedirs('/mnt/muffi', exist_ok=True)

with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

changed = False
out = []
for line in lines:
    if line.lstrip().startswith('#') or not line.strip():
        out.append(line)
        continue

    parts = line.split()
    if len(parts) >= 2 and parts[1] == '/mnt/muffi':
        parts[0] = target
        line = '\t'.join(parts) + '\n'
        changed = True
    out.append(line)

if not changed:
    out.append(
        f"{target}\t/mnt/muffi\tcifs\t"
        f"credentials={cred_file},uid=1000,gid=1000,iocharset=utf8,vers=3.0,_netdev,nofail,x-systemd.automount\t0\t0\n"
    )
    changed = True

backup = f"{path}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
shutil.copy2(path, backup)
with open(path, 'w', encoding='utf-8') as f:
    f.writelines(out)
print(backup)
'''

    shell_cmd = (
        "python3 - <<'PY' \"$1\" \"$2\" \"$3\"\n" + fstab_script + "\nPY\n"
        "systemctl daemon-reload >/dev/null 2>&1 || true; "
        "systemctl reset-failed mnt-muffi.mount mnt-muffi.automount >/dev/null 2>&1 || true; "
        "umount -l /mnt/muffi >/dev/null 2>&1 || true; "
        "mount /mnt/muffi"
    )

    cmd = ["sudo", "-S", "-p", "", "sh", "-lc", shell_cmd, "--", target_source_fstab, smb_user, smb_pass]
    try:
        proc = subprocess.run(
            cmd,
            input=pw + "\n",
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if proc.returncode != 0:
        # Falls bereits korrekt gemountet, als Erfolg behandeln.
        current = get_network_mount_source_for_photo_dir()
        if current and current.lower() == target_source.lower():
            return {"ok": True, "message": f"Share bereits aktiv: {target_source}", "targetSource": target_source}
        msg = (proc.stderr or proc.stdout or "Share-Wechsel fehlgeschlagen").strip()
        return {"ok": False, "error": msg[:500]}

    update_storage_auth({"username": smb_user, "password": smb_pass})
    return {"ok": True, "message": f"Share gewechselt auf {target_source}", "targetSource": target_source}


def get_orientation(filepath):
    """Gibt 'landscape' oder 'portrait' zurück (nach EXIF-Korrektur)"""
    try:
        img = Image.open(filepath)
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        return "landscape" if w > h else "portrait"
    except:
        return "portrait"


def resize_image(filepath, orientation):
    """Bild öffnen, EXIF korrigieren, auf Display-Größe skalieren"""
    img = Image.open(filepath).convert("RGB")
    img = ImageOps.exif_transpose(img)

    if orientation == "landscape":
        # Querformat: Display ist 320x172
        target_w, target_h = DISPLAY_H, DISPLAY_W
    else:
        # Hochformat: Display ist 172x320
        target_w, target_h = DISPLAY_W, DISPLAY_H

    # Skalieren mit Letterbox (schwarze Balken)
    img.thumbnail((target_w, target_h), Image.LANCZOS)

    # Auf exakte Zielgröße mit schwarzem Hintergrund
    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    offset_x = (target_w - img.width) // 2
    offset_y = (target_h - img.height) // 2
    canvas.paste(img, (offset_x, offset_y))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def list_photos():
    """Liefert Metadaten für alle Bilder im PHOTO_DIR."""
    photo_dir = get_photo_dir()
    if not safe_isdir(photo_dir):
        return []

    try:
        files = sorted([
            f for f in os.listdir(photo_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ])
    except OSError:
        return []

    # Cache aufräumen (gelöschte Dateien entfernen)
    existing = set(files)
    for k in list(ORIENTATION_CACHE.keys()):
        if k not in existing:
            ORIENTATION_CACHE.pop(k, None)

    file_info = []
    # Pro Request nur begrenzt neue Orientierungen scannen, damit /list schnell bleibt
    scan_budget = 8
    for f in files:
        fp = os.path.join(photo_dir, f)
        ori = ORIENTATION_CACHE.get(f)
        if ori is None:
            if scan_budget > 0:
                ori = get_orientation(fp)
                ORIENTATION_CACHE[f] = ori
                scan_budget -= 1
            else:
                ori = "portrait"
        try:
            size_bytes = os.path.getsize(fp)
        except:
            size_bytes = 0
        file_info.append({
            "name": f,
            "orientation": ori,
            "sizeBytes": size_bytes,
            "url": f"/{quote(f)}"
        })
    return file_info


SERVER_CONFIG = load_config()


class FrameHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[Frame] {self.address_string()} - {fmt % args}")

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False)
        out = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def send_html(self, html, status=200):
        out = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def send_ui_v2_file(self, filename):
        content_type = UI_V2_FILES.get(filename)
        if not content_type:
            self.send_error(404, "Not found")
            return

        filepath = os.path.join(UI_V2_DIR, filename)
        if not os.path.isfile(filepath):
            self.send_error(404, "Not found")
            return

        with open(filepath, "rb") as f:
            data = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def render_dashboard(self, file_info):
        frame = get_frame_state_snapshot()
        led = get_led_config_snapshot()
        frame_html = "<p>Noch keine Rückmeldung vom Rahmen.</p>"
        if frame.get("filename"):
            frame_name = frame.get("filename")
            frame_ori = frame.get("orientation") or "?"
            frame_idx_raw = frame.get("index")
            frame_cnt_raw = frame.get("count")
            frame_idx = int(frame_idx_raw if frame_idx_raw is not None else -1)
            frame_cnt = int(frame_cnt_raw if frame_cnt_raw is not None else 0)
            frame_pos = f"{frame_idx + 1}/{frame_cnt}" if frame_idx >= 0 and frame_cnt > 0 else "-"
            frame_missing = " (Datei fehlt)" if not frame.get("exists") else ""
            frame_html = (
                f'<img id="frame-current-image" src="/{quote(frame_name)}?t={int(frame.get("updatedAt") or 0)}" alt="frame-current" style="max-width:100%;border-radius:12px;border:1px solid #ddd;" />'
                f'<p><b id="frame-current-name">{escape(frame_name)}</b>{frame_missing}</p>'
                f'<p id="frame-current-meta">{frame_ori} · Pos {frame_pos}</p>'
                f'<p><button id="delete-current-btn" data-name="{escape(frame_name)}">🗑️ Dieses Bild löschen</button></p>'
                f'<div id="delete-msg"></div>'
            )

        active_photo_dir = get_photo_dir()
        photo_dir_ok = safe_isdir(active_photo_dir)
        mount_ok = safe_ismount(PHOTO_DIR)
        storage_mode = "netzwerk" if active_photo_dir == PHOTO_DIR else "lokal (fallback)"
        refresh_seconds = SERVER_CONFIG.get("refreshMs", DEFAULT_REFRESH_MS) // 1000

        return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Muffi Frame Server</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; color: #222; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; margin-bottom: 16px; }}
    .ok {{ color: #0a7d2e; font-weight: 600; }}
    .bad {{ color: #b00020; font-weight: 600; }}
    .row {{ display:flex; gap:8px; align-items:center; flex-wrap: wrap; }}
    input {{ font-size: 16px; padding: 8px; }}
    input[type=number] {{ width: 140px; }}
    input[type=range] {{ width: min(320px, 100%); }}
    input[type=color] {{ width: 64px; height: 40px; padding: 2px; border: 1px solid #d1d5db; border-radius: 8px; }}
    button {{ font-size: 16px; padding: 8px 12px; cursor: pointer; }}
    .mini {{ font-size: 12px; color:#666; }}
    #cfg-msg,#upload-msg,#delete-msg,#frame-msg,#led-msg {{ font-size: 14px; color: #444; margin-top: 6px; min-height: 1.2em; }}
    #upload-progress {{ width: min(520px, 100%); height: 20px; }}
    a {{ text-decoration: none; }}
  </style>
</head>
<body>
  <h1>🖼️ Muffi Frame Server</h1>

  <div class="card">
    <h2>Status</h2>
    <p>Foto-Ordner (aktiv): <code>{escape(active_photo_dir)}</code> <span class="mini">[{escape(storage_mode)}]</span></p>
    <p>Netzwerk-Ordner (konfiguriert): <code>{escape(PHOTO_DIR)}</code></p>
    <p>Ordner vorhanden: <span class="{'ok' if photo_dir_ok else 'bad'}">{'ja' if photo_dir_ok else 'nein'}</span></p>
    <p>Mount aktiv: <span class="{'ok' if mount_ok else 'bad'}">{'ja' if mount_ok else 'nein'}</span></p>
    <p>Bilder gesamt: <b>{len(file_info)}</b></p>
    <p>
      <a href="/gallery">📚 Galerie</a> ·
      <a href="/api/list">🔌 API (/api/list)</a> ·
      <a href="/list">🔌 API (/list)</a>
    </p>
  </div>

  <div class="card">
    <h2>Rahmen Intervall</h2>
    <p>Aktuell: <b><span id="current-seconds">{refresh_seconds}</span> Sekunden</b></p>
    <form id="cfg-form" class="row">
      <label for="refreshSeconds">Freie Zeitwahl (Sekunden):</label>
      <input id="refreshSeconds" name="refreshSeconds" type="number" min="10" max="86400" value="{refresh_seconds}" required />
      <button type="submit">Speichern</button>
    </form>
    <div id="cfg-msg"></div>
  </div>

  <div class="card">
    <h2>LED am Rahmen</h2>
    <div class="row">
      <label><input type="checkbox" id="led-on" {'checked' if led.get('on') else ''} /> LED an</label>
      <span class="mini">Quelle: <span id="led-source">{escape(str(led.get('source') or '-'))}</span></span>
    </div>
    <div class="row" style="margin-top:8px;">
      <label for="led-brightness">Helligkeit</label>
      <input id="led-brightness" type="range" min="0" max="255" value="{int(led.get('brightness') or 0)}" />
      <b><span id="led-brightness-val">{int(led.get('brightness') or 0)}</span></b>
    </div>
    <div class="row" style="margin-top:8px;">
      <label for="led-color">Farbe</label>
      <input id="led-color" type="color" value="{escape(str(led.get('color') or '#FFD6A0'))}" />
      <button type="button" id="led-next-color">Nächste Katalogfarbe</button>
    </div>
    <div class="row" style="margin-top:8px;">
      <label for="led-order">LED Reihenfolge</label>
      <select id="led-order">
        <option value="GRB" {'selected' if led.get('ledOrder') == 'GRB' else ''}>GRB (Waveshare Default)</option>
        <option value="RGB" {'selected' if led.get('ledOrder') == 'RGB' else ''}>RGB</option>
        <option value="BRG" {'selected' if led.get('ledOrder') == 'BRG' else ''}>BRG</option>
        <option value="BGR" {'selected' if led.get('ledOrder') == 'BGR' else ''}>BGR</option>
        <option value="RBG" {'selected' if led.get('ledOrder') == 'RBG' else ''}>RBG</option>
        <option value="GBR" {'selected' if led.get('ledOrder') == 'GBR' else ''}>GBR</option>
      </select>
    </div>
    <div class="mini">ESP: Doppelklick auf BOOT = nächste Farbe, Seitentaste = nächste Farbe.</div>
    <div id="led-msg"></div>
  </div>

  <div class="card">
    <h2>Bild Upload</h2>
    <form id="upload-form" class="row">
      <input id="upload-file" type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" required />
      <button type="submit">Upload</button>
    </form>
    <p><progress id="upload-progress" max="100" value="0"></progress></p>
    <div id="upload-msg"></div>
  </div>

  <div class="card">
    <h2>Aktuell auf dem Rahmen</h2>
    {frame_html}
    <div id="frame-msg"></div>
  </div>

  <script>
    const form = document.getElementById('cfg-form');
    const msg = document.getElementById('cfg-msg');
    const current = document.getElementById('current-seconds');

    const ledOnEl = document.getElementById('led-on');
    const ledBrightnessEl = document.getElementById('led-brightness');
    const ledBrightnessValEl = document.getElementById('led-brightness-val');
    const ledColorEl = document.getElementById('led-color');
    const ledOrderEl = document.getElementById('led-order');
    const ledMsgEl = document.getElementById('led-msg');
    const ledSourceEl = document.getElementById('led-source');
    const ledNextColorBtn = document.getElementById('led-next-color');

    form.addEventListener('submit', async (e) => {{
      e.preventDefault();
      msg.textContent = 'Speichere…';
      const seconds = Number(document.getElementById('refreshSeconds').value || 0);
      try {{
        const res = await fetch('/api/config', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ refreshMs: seconds * 1000 }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Fehler');
        const sec = Math.floor((data.refreshMs || 0) / 1000);
        current.textContent = sec;
        document.getElementById('refreshSeconds').value = sec;
        msg.textContent = '✅ Gespeichert. ESP nutzt den Wert beim nächsten Refresh automatisch.';
      }} catch (err) {{
        msg.textContent = '❌ ' + err.message;
      }}
    }});

    async function setLedConfig(patch) {{
      try {{
        const res = await fetch('/api/led', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(patch || {{}})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Fehler');
        if (ledOnEl) ledOnEl.checked = !!data.on;
        if (ledBrightnessEl) ledBrightnessEl.value = Number(data.brightness || 0);
        if (ledBrightnessValEl) ledBrightnessValEl.textContent = String(Number(data.brightness || 0));
        if (ledColorEl && data.color) ledColorEl.value = data.color;
        if (ledOrderEl && data.ledOrder) ledOrderEl.value = data.ledOrder;
        if (ledSourceEl) ledSourceEl.textContent = data.source || '-';
        if (ledMsgEl) ledMsgEl.textContent = '✅ LED gespeichert';
      }} catch (err) {{
        if (ledMsgEl) ledMsgEl.textContent = '❌ ' + err.message;
      }}
    }}

    async function refreshLedConfig() {{
      try {{
        const res = await fetch('/api/led');
        const data = await res.json();
        if (!res.ok) return;
        if (ledOnEl) ledOnEl.checked = !!data.on;
        if (ledBrightnessEl) ledBrightnessEl.value = Number(data.brightness || 0);
        if (ledBrightnessValEl) ledBrightnessValEl.textContent = String(Number(data.brightness || 0));
        if (ledColorEl && data.color) ledColorEl.value = data.color;
        if (ledOrderEl && data.ledOrder) ledOrderEl.value = data.ledOrder;
        if (ledSourceEl) ledSourceEl.textContent = data.source || '-';
      }} catch (_) {{}}
    }}

    let ledSaveTimer = null;
    function queueLedSave(patch) {{
      if (ledSaveTimer) clearTimeout(ledSaveTimer);
      if (ledMsgEl) ledMsgEl.textContent = 'Speichere…';
      ledSaveTimer = setTimeout(() => setLedConfig(patch), 120);
    }}

    if (ledOnEl) ledOnEl.addEventListener('change', () => setLedConfig({{ on: !!ledOnEl.checked, source: 'web' }}));
    if (ledBrightnessEl) ledBrightnessEl.addEventListener('input', () => {{
      const v = Number(ledBrightnessEl.value || 0);
      if (ledBrightnessValEl) ledBrightnessValEl.textContent = String(v);
      queueLedSave({{ brightness: v, source: 'web' }});
    }});
    if (ledColorEl) ledColorEl.addEventListener('input', () => {{
      queueLedSave({{ color: ledColorEl.value, colorIndex: -1, source: 'web' }});
    }});
    if (ledOrderEl) ledOrderEl.addEventListener('change', () => {{
      setLedConfig({{ ledOrder: ledOrderEl.value, source: 'web' }});
    }});
    if (ledNextColorBtn) ledNextColorBtn.addEventListener('click', async () => {{
      try {{
        const res = await fetch('/api/led');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Fehler');
        const catalog = Array.isArray(data.catalog) ? data.catalog : [];
        const idx = Number(data.colorIndex ?? -1);
        const next = catalog.length ? ((idx >= 0 ? idx : -1) + 1) % catalog.length : -1;
        if (next >= 0) {{
          await setLedConfig({{ color: catalog[next].hex, colorIndex: next, on: true, source: 'web' }});
        }}
      }} catch (err) {{
        if (ledMsgEl) ledMsgEl.textContent = '❌ ' + err.message;
      }}
    }});

    refreshLedConfig();
    setInterval(refreshLedConfig, 2500);

    const uploadForm = document.getElementById('upload-form');
    const uploadFile = document.getElementById('upload-file');
    const uploadMsg = document.getElementById('upload-msg');
    const uploadProgress = document.getElementById('upload-progress');
    const deleteBtn = document.getElementById('delete-current-btn');
    const deleteMsg = document.getElementById('delete-msg');

    const frameMsg = document.getElementById('frame-msg');

    async function refreshFrameState() {{
      try {{
        const res = await fetch('/api/frame-state');
        const data = await res.json();
        if (!res.ok) return;
        const nmEl = document.getElementById('frame-current-name');
        const imgEl = document.getElementById('frame-current-image');
        const metaEl = document.getElementById('frame-current-meta');

        if (data.filename && nmEl && imgEl && metaEl) {{
          const idx = Number(data.index ?? -1);
          const cnt = Number(data.count ?? 0);
          const pos = (idx >= 0 && cnt > 0) ? ((idx + 1) + '/' + cnt) : '-';
          nmEl.textContent = data.filename + (data.exists ? '' : ' (Datei fehlt)');
          metaEl.textContent = (data.orientation || '?') + ' · Pos ' + pos;
          imgEl.src = '/' + encodeURIComponent(data.filename) + '?t=' + Date.now();
          if (deleteBtn) deleteBtn.setAttribute('data-name', data.filename);
          if (frameMsg) frameMsg.textContent = '';
        }} else if (frameMsg) {{
          frameMsg.textContent = 'Noch keine Rückmeldung vom Rahmen.';
        }}
      }} catch (_) {{}}
    }}

    async function deleteImageByName(name) {{
      if (!name) return;
      if (!confirm('Bild wirklich löschen?\\n' + name)) return;
      if (deleteMsg) deleteMsg.textContent = 'Lösche…';
      try {{
        const res = await fetch('/api/delete', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ name }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Fehler');
        if (deleteMsg) deleteMsg.textContent = '✅ Gelöscht: ' + (data.filename || name);
        setTimeout(() => window.location.reload(), 400);
      }} catch (err) {{
        if (deleteMsg) deleteMsg.textContent = '❌ ' + err.message;
      }}
    }}

    if (deleteBtn) {{
      deleteBtn.addEventListener('click', (e) => {{
        e.preventDefault();
        const n = deleteBtn.getAttribute('data-name') || '';
        deleteImageByName(n);
      }});
    }}

    refreshFrameState();
    setInterval(refreshFrameState, 2500);

    uploadForm.addEventListener('submit', (e) => {{
      e.preventDefault();
      const file = uploadFile.files && uploadFile.files[0];
      if (!file) {{
        uploadMsg.textContent = '❌ Bitte eine Datei wählen.';
        return;
      }}

      uploadMsg.textContent = 'Upload läuft…';
      uploadProgress.value = 0;

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');

      xhr.upload.onprogress = (ev) => {{
        if (ev.lengthComputable) {{
          const p = Math.max(0, Math.min(100, Math.round((ev.loaded / ev.total) * 100)));
          uploadProgress.value = p;
          uploadMsg.textContent = 'Upload läuft… ' + p + '%';
        }}
      }};

      xhr.onerror = () => {{
        uploadMsg.textContent = '❌ Upload fehlgeschlagen (Netzwerk).';
      }};

      xhr.onload = () => {{
        let data = {{}};
        try {{ data = JSON.parse(xhr.responseText || '{{}}'); }} catch (_) {{}}
        if (xhr.status >= 200 && xhr.status < 300) {{
          uploadProgress.value = 100;
          uploadMsg.textContent = '✅ Upload fertig: ' + (data.filename || file.name);
          if (deleteBtn && data.filename) deleteBtn.setAttribute('data-name', data.filename);
          refreshFrameState();
        }} else {{
          uploadMsg.textContent = '❌ ' + (data.error || ('Upload fehlgeschlagen (' + xhr.status + ')'));
        }}
      }};

      xhr.send(file);
    }});
  </script>
</body>
</html>"""

    def render_gallery(self, file_info):
        items = []
        for f in reversed(file_info):
            size_kb = max(1, f.get("sizeBytes", 0) // 1024)
            items.append(
                f"""
                <div class="item">
                  <a href="/{quote(f['name'])}" target="_blank">
                    <img loading="lazy" src="/{quote(f['name'])}" alt="{escape(f['name'])}" />
                  </a>
                  <div class="meta">{escape(f['name'])}</div>
                  <div class="sub">{f['orientation']} · {size_kb} KB</div>
                  <button class="del-btn" data-name="{escape(f['name'])}">🗑️ Löschen</button>
                </div>
                """
            )

        gallery = "\n".join(items) if items else "<p>Keine Bilder gefunden.</p>"

        return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Muffi Galerie</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; color: #222; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }}
    .item {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 8px; }}
    img {{ width: 100%; height: 180px; object-fit: cover; border-radius: 8px; background: #000; }}
    .meta {{ font-size: 13px; margin-top: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .sub {{ font-size: 12px; color: #666; }}
    .del-btn {{ margin-top: 6px; font-size: 13px; padding: 6px 8px; cursor: pointer; }}
    a {{ text-decoration: none; }}
  </style>
</head>
<body>
  <h1>📚 Muffi Galerie</h1>
  <p><a href="/">⬅ Zurück zum Dashboard</a></p>
  <div class="grid">{gallery}</div>
  <script>
    async function deleteImage(name) {{
      if (!name) return;
      if (!confirm('Bild wirklich löschen?\\n' + name)) return;
      try {{
        const res = await fetch('/api/delete', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ name }})
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Fehler');
        window.location.reload();
      }} catch (err) {{
        alert('Löschen fehlgeschlagen: ' + err.message);
      }}
    }}
    document.querySelectorAll('.del-btn').forEach(btn => {{
      btn.addEventListener('click', (e) => {{
        e.preventDefault();
        deleteImage(btn.getAttribute('data-name') || '');
      }});
    }});
  </script>
</body>
</html>"""

    def do_GET(self):
        parsed = urlparse(self.path)
        raw_path = parsed.path
        path = unquote(raw_path.strip("/"))

        # UI V2 ist jetzt Standard-Startseite
        if path in ("", "index.html"):
            self.send_ui_v2_file("index.html")
            return

        if path in ("ui-v2", "ui-v2/"):
            self.send_ui_v2_file("index.html")
            return

        if path.startswith("ui-v2/"):
            filename = path[len("ui-v2/"):].strip()
            if filename == "":
                filename = "index.html"
            self.send_ui_v2_file(filename)
            return

        file_info = list_photos()

        # Klassisches Dashboard weiter verfügbar
        if path in ("classic", "classic.html"):
            self.send_html(self.render_dashboard(file_info))
            return

        if path in ("gallery", "gallery.html"):
            self.send_html(self.render_gallery(file_info))
            return

        # Config API
        if path == "api/config":
            self.send_json({
                "refreshMs": SERVER_CONFIG.get("refreshMs", DEFAULT_REFRESH_MS),
                "minRefreshMs": MIN_REFRESH_MS,
                "maxRefreshMs": MAX_REFRESH_MS
            })
            return

        if path == "api/status":
            storage = get_storage_state()
            self.send_json({
                "photoDir": storage.get("network", {}).get("path", PHOTO_DIR),
                "activePhotoDir": storage.get("activePath", get_photo_dir()),
                "photoDirExists": safe_isdir(storage.get("activePath", get_photo_dir())),
                "mountActive": bool(storage.get("network", {}).get("mount")),
                "usingFallback": storage.get("activeSource") != "network",
                "storage": storage,
                "count": len(file_info),
            })
            return

        if path == "api/storage":
            self.send_json(get_storage_config_snapshot())
            return

        if path == "api/storage/diagnostics":
            self.send_json(get_storage_diagnostics())
            return

        if path == "api/update/status":
            qs_params = parse_qs(parsed.query or "")
            offset = qs_params.get("offset", [0])[0]
            self.send_json(get_update_status(offset=offset))
            return

        if path == "api/esp/update/status":
            qs_params = parse_qs(parsed.query or "")
            offset = qs_params.get("offset", [0])[0]
            self.send_json(get_esp_update_status(offset=offset))
            return

        if path == "api/esp/usb/status":
            self.send_json(get_esp_usb_status())
            return

        if path == "api/esp/usb/flash/status":
            qs_params = parse_qs(parsed.query or "")
            offset = qs_params.get("offset", [0])[0]
            self.send_json(get_esp_usb_flash_status(offset=offset))
            return

        if path == "api/esp/sync-status":
            self.send_json(get_esp_sync_status())
            return

        if path == "api/storage/auth":
            self.send_json(get_storage_auth_snapshot(mask_password=True))
            return

        if path == "api/upload-status":
            self.send_json(get_upload_status_snapshot())
            return

        if path == "api/frame-state":
            self.send_json(get_frame_state_snapshot())
            return

        if path == "api/led":
            self.send_json(get_led_config_snapshot())
            return

        if path == "api/motor":
            self.send_json(get_motor_config_snapshot())
            return

        if path == "api/wlan":
            client_ip = ""
            try:
                client_ip = str((self.client_address or [""])[0] or "")
            except Exception:
                client_ip = ""

            wlan = get_wlan_config_snapshot(mask_password=False)
            ua = str(self.headers.get("User-Agent", "") or "")
            esp_host = str(wlan.get("espHost", "") or "")
            qs_params = parse_qs(parsed.query or "")
            source = str((qs_params.get("source") or [""])[0] or "").strip().lower()
            from_esp = (source == "esp") or ("ESP" in ua.upper()) or (esp_host and client_ip and client_ip == esp_host)

            sync = get_esp_sync_snapshot()
            if from_esp:
                sync = mark_esp_wlan_pull(client_ip)
            wlan["syncToken"] = str(sync.get("desiredToken") or "")
            self.send_json(wlan)
            return

        # ─── SMB Network Browser API ────────────────────────────────────────────
        if path == "api/smb/discover":
            hosts = smb_discover_hosts(timeout=5)
            self.send_json({"hosts": hosts})
            return

        if path == "api/smb/shares":
            qs_params = parse_qs(parsed.query or "")
            host     = qs_params.get("host", [""])[0].strip()
            user     = qs_params.get("user", [""])[0].strip()
            pw       = qs_params.get("pw",   [""])[0].strip()
            if not host:
                self.send_json({"error": "Missing host", "shares": []}, 400)
                return
            shares, ok, err = smb_list_shares(host, user, pw)
            self.send_json({"shares": shares, "ok": ok, "error": err})
            return

        if path == "api/smb/browse":
            qs_params   = parse_qs(parsed.query or "")
            host        = qs_params.get("host",  [""])[0].strip()
            share       = qs_params.get("share", [""])[0].strip()
            folder_path = qs_params.get("path",  [""])[0].strip()
            user        = qs_params.get("user",  [""])[0].strip()
            pw          = qs_params.get("pw",    [""])[0].strip()
            if not host or not share:
                self.send_json({"error": "Missing host or share", "entries": []}, 400)
                return
            entries, ok, err = smb_browse_folder(host, share, folder_path, user, pw)
            self.send_json({"entries": entries, "ok": ok, "error": err})
            return
        # ─── end SMB Network Browser API ──────────────────────────────────────────

        # Dateiliste: /list bleibt schlank für ESP, /api/list ist voll für Web/Tools
        if path == "list":
            # ESP hat nur 200 Slots im Sketch -> nur die neuesten 200 liefern
            esp_src = file_info[-200:]
            esp_files = [{"name": f["name"], "orientation": f["orientation"]} for f in esp_src]
            self.send_json({
                "files": esp_files,
                "latest": esp_files[-1] if esp_files else None,
                "count": len(esp_files)
            })
            return

        if path == "api/list":
            self.send_json({
                "files": file_info,
                "latest": file_info[-1] if file_info else None,
                "count": len(file_info)
            })
            return

        # Einzelnes Bild (automatisch skaliert)
        photo_root = os.path.abspath(get_photo_dir())
        filepath = os.path.abspath(os.path.join(photo_root, path))

        # path traversal blocken
        if not (filepath == photo_root or filepath.startswith(photo_root + os.sep)):
            self.send_error(403, "Forbidden")
            return

        if not os.path.isfile(filepath):
            self.send_error(404, "Not found")
            return

        try:
            ori = get_orientation(filepath)
            data = resize_image(filepath, ori)

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Orientation", ori)
            self.end_headers()
            self.wfile.write(data)
            print(f"  → {path} [{ori}] {len(data)//1024}KB")

        except Exception as e:
            print(f"  Fehler: {e}")
            self.send_error(500, str(e))

    def do_POST(self):
        parsed = urlparse(self.path)
        raw_path = parsed.path
        path = unquote(raw_path.strip("/"))

        if path == "api/config":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            ctype = (self.headers.get("Content-Type") or "").lower()

            refresh_ms = None
            try:
                if "application/json" in ctype:
                    payload = json.loads(body.decode("utf-8") or "{}")
                    refresh_ms = payload.get("refreshMs")
                else:
                    params = parse_qs(body.decode("utf-8"))
                    if "refreshMs" in params:
                        refresh_ms = params.get("refreshMs", [None])[0]
                    elif "refreshSeconds" in params:
                        val = params.get("refreshSeconds", [None])[0]
                        if val is not None:
                            refresh_ms = int(val) * 1000
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            if refresh_ms is None:
                self.send_json({"error": "refreshMs oder refreshSeconds fehlt"}, status=400)
                return

            with CONFIG_LOCK:
                SERVER_CONFIG["refreshMs"] = clamp_refresh_ms(refresh_ms)
                try:
                    save_config(SERVER_CONFIG)
                except Exception as e:
                    self.send_json({"error": f"Speichern fehlgeschlagen: {e}"}, status=500)
                    return
                saved_refresh_ms = SERVER_CONFIG["refreshMs"]

            self.send_json({
                "ok": True,
                "refreshMs": saved_refresh_ms,
                "refreshSeconds": saved_refresh_ms // 1000
            })
            return

        if path == "api/frame-state":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            filename = sanitize_filename(payload.get("filename", ""))
            orientation = str(payload.get("orientation", "") or "")
            index = payload.get("index", -1)
            count = payload.get("count", 0)
            source = self.client_address[0] if self.client_address else ""

            if filename:
                update_frame_state(filename=filename, orientation=orientation, index=index, count=count, source=source)
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "filename fehlt"}, status=400)
            return

        if path == "api/led":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            try:
                out = update_led_config(payload or {})
            except Exception as e:
                self.send_json({"error": f"LED speichern fehlgeschlagen: {e}"}, status=500)
                return

            self.send_json({"ok": True, **out})
            return

        if path == "api/motor":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            try:
                out = update_motor_config(payload or {})
            except Exception as e:
                self.send_json({"error": f"Motor speichern fehlgeschlagen: {e}"}, status=500)
                return

            self.send_json({"ok": True, **out})
            return

        if path == "api/storage":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            try:
                out = update_storage_config(payload or {})
            except Exception as e:
                self.send_json({"error": f"Storage speichern fehlgeschlagen: {e}"}, status=500)
                return

            self.send_json({"ok": True, **out})
            return

        if path == "api/storage/share-check":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            analysis = analyze_network_path_input((payload or {}).get("networkPath"))
            mapped = analysis.get("mappedPath")
            self.send_json({
                "ok": not bool(analysis.get("blocked")),
                "blocked": bool(analysis.get("blocked")),
                "shareSwitchRequired": bool(analysis.get("shareSwitchRequired")),
                "mappedPath": mapped,
                "normalizedFrom": analysis.get("normalizedFrom", ""),
                "hint": analysis.get("hint", ""),
                "mountSource": analysis.get("mountSource", ""),
            })
            return

        if path == "api/update/start":
            result = start_update_job()
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "Update konnte nicht gestartet werden")}, status=409)
                return
            self.send_json({"ok": True, "message": result.get("message", "Update gestartet")})
            return

        if path == "api/esp/prepare":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            payload = {}
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                payload = {}

            if payload:
                try:
                    update_wlan_config(payload)
                except Exception as e:
                    self.send_json({"ok": False, "error": f"WLAN speichern fehlgeschlagen: {e}"}, status=500)
                    return

            sync = mark_esp_prepare_requested()
            status_payload = get_esp_sync_status()
            self.send_json({
                "ok": True,
                "message": "ESP Vorbereitung gespeichert. Warte auf WLAN-Sync vom ESP.",
                "syncToken": sync.get("desiredToken", ""),
                **status_payload,
            })
            return

        if path == "api/esp/usb/check-boot":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            port = ""
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
                port = str((payload or {}).get("port") or "").strip()
            except Exception:
                pass

            result = check_esp_boot_mode(port)
            if result.get("ok"):
                self.send_json({"ok": True, "message": result.get("message", "Boot-Modus ok"), "details": result.get("details", ""), "port": port})
            else:
                self.send_json({"ok": False, "error": result.get("error", "Boot-Check fehlgeschlagen"), "details": result.get("details", ""), "port": port}, status=502)
            return

        if path == "api/esp/usb/flash/start":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            port = ""
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
                port = str((payload or {}).get("port") or "").strip()
            except Exception:
                pass

            result = start_esp_usb_flash_job(port)
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "USB-Flash konnte nicht gestartet werden")}, status=409)
                return
            self.send_json({"ok": True, "message": result.get("message", "USB-Flash gestartet"), "port": result.get("port", port)})
            return

        if path == "api/esp/update/start":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            host = ""
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
                host = str((payload or {}).get("espHost") or "").strip()
            except Exception:
                pass

            result = start_esp_update_job(host)
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "ESP-Update konnte nicht gestartet werden")}, status=409)
                return
            self.send_json({"ok": True, "message": result.get("message", "ESP-Update gestartet"), "espHost": result.get("espHost", host)})
            return

        if path == "api/server/restart":
            result = trigger_server_restart(delay_seconds=1.0)
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "Restart konnte nicht ausgelöst werden")}, status=500)
                return
            self.send_json({"ok": True, "message": result.get("message", "Restart ausgelöst")})
            return

        if path == "api/storage/auth":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            username = str((payload or {}).get("username") or "").strip()
            password_share = str((payload or {}).get("password") or "")

            if not username or not password_share:
                self.send_json({"ok": False, "error": "Benutzer und Passwort sind erforderlich"}, status=400)
                return

            update_storage_auth({"username": username, "password": password_share})
            self.send_json({"ok": True, **get_storage_auth_snapshot(mask_password=True)})
            return

        if path == "api/storage/auth/test":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            username = str((payload or {}).get("username") or "").strip()
            password_share = str((payload or {}).get("password") or "")
            network_path = str((payload or {}).get("networkPath") or "")

            if not username or not password_share:
                saved = sanitize_storage_auth((SERVER_CONFIG or {}).get("storageAuth", {}))
                username = username or saved.get("username", "")
                password_share = password_share or saved.get("password", "")

            result = test_share_credentials(username, password_share, network_path)
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "SMB Test fehlgeschlagen"), "host": result.get("host", ""), "share": result.get("share", "")}, status=502)
                return

            self.send_json({"ok": True, "message": result.get("message", "SMB Test ok"), "host": result.get("host", ""), "share": result.get("share", "")})
            return

        if path == "api/storage/remount":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            result = remount_network_share(
                (payload or {}).get("password"),
                (payload or {}).get("shareUser"),
                (payload or {}).get("sharePassword"),
            )
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "Remount fehlgeschlagen")}, status=403)
                return

            self.send_json({"ok": True, "message": result.get("message", "ok")})
            return

        if path == "api/storage/share-switch":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            raw_path = str((payload or {}).get("networkPath") or "")
            result = switch_network_share(
                (payload or {}).get("password"),
                raw_path,
                (payload or {}).get("shareUser"),
                (payload or {}).get("sharePassword"),
            )
            if not result.get("ok"):
                self.send_json({"ok": False, "error": result.get("error", "Share-Wechsel fehlgeschlagen")}, status=403)
                return

            # Nach Share-Wechsel gewünschten Pfad erneut anwenden
            try:
                out = update_storage_config({"mode": "network", "networkPath": raw_path})
            except Exception:
                out = get_storage_state()

            self.send_json({"ok": True, "message": result.get("message", "ok"), **out})
            return

        if path == "api/wlan":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_json({"error": f"Ungültige Daten: {e}"}, status=400)
                return

            try:
                out = update_wlan_config(payload or {})
            except Exception as e:
                self.send_json({"error": f"WLAN speichern fehlgeschlagen: {e}"}, status=500)
                return

            self.send_json({"ok": True, **out})
            return

        if path == "api/wlan/test":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            host = ""
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
                host = str(payload.get("espHost") or "").strip()
            except Exception:
                pass

            if not host:
                host = get_wlan_config_snapshot(mask_password=False).get("espHost", "")

            result = test_esp_host(host, port=80, timeout_seconds=1.8)
            if result.get("ok"):
                self.send_json({"ok": True, "espHost": host, "mode": result.get("mode", "unknown"), "message": result.get("message", "ESP erreichbar")})
            else:
                self.send_json({"ok": False, "espHost": host, "error": result.get("error", "nicht erreichbar")}, status=502)
            return

        if path == "api/delete":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

            name = ""
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
                name = sanitize_filename(payload.get("name", ""))
            except Exception:
                pass

            if not name:
                self.send_json({"error": "Dateiname fehlt"}, status=400)
                return

            photo_root = os.path.abspath(get_photo_dir())
            target = os.path.abspath(os.path.join(photo_root, name))
            if not target.startswith(photo_root + os.sep):
                self.send_json({"error": "Ungültiger Dateiname"}, status=400)
                return

            if not os.path.isfile(target):
                self.send_json({"error": "Datei nicht gefunden"}, status=404)
                return

            try:
                os.remove(target)
                ORIENTATION_CACHE.pop(name, None)
                frame = get_frame_state_snapshot()
                if frame.get("filename") == name:
                    update_frame_state(filename=name, orientation=frame.get("orientation", ""), index=frame.get("index", -1), count=frame.get("count", 0), source=frame.get("source", ""))
                self.send_json({"ok": True, "filename": name})
            except Exception as e:
                self.send_json({"error": f"Löschen fehlgeschlagen: {e}"}, status=500)
            return

        if path == "api/upload":
            photo_root = os.path.abspath(get_photo_dir())

            params = parse_qs(parsed.query or "")
            requested_name = params.get("name", [""])[0]
            filename = sanitize_filename(requested_name)
            if not filename:
                self.send_json({"error": "Dateiname fehlt"}, status=400)
                return

            ext = os.path.splitext(filename)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png"):
                self.send_json({"error": "Nur JPG/PNG erlaubt"}, status=400)
                return

            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except:
                length = 0

            if length <= 0:
                self.send_json({"error": "Leerer Upload"}, status=400)
                return
            if length > MAX_UPLOAD_BYTES:
                self.send_json({"error": f"Datei zu groß (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)"}, status=413)
                return

            final_path = os.path.abspath(os.path.join(photo_root, filename))
            if not final_path.startswith(photo_root + os.sep):
                self.send_json({"error": "Ungültiger Dateiname"}, status=400)
                return

            tmp_path = os.path.abspath(os.path.join(photo_root, f".__upload_{int(time.time())}_{filename}.part"))

            update_upload_status(active=True, phase="uploading", progress=0, filename=filename, message="Upload läuft")

            try:
                os.makedirs(photo_root, exist_ok=True)
                chunk_size = 64 * 1024
                received = 0

                with open(tmp_path, "wb") as out:
                    while received < length:
                        want = min(chunk_size, length - received)
                        chunk = self.rfile.read(want)
                        if not chunk:
                            raise RuntimeError("Upload unterbrochen")
                        out.write(chunk)
                        received += len(chunk)
                        progress = int((received * 100) / length)
                        if progress > 100:
                            progress = 100
                        update_upload_status(
                            active=True,
                            phase="uploading",
                            progress=progress,
                            filename=filename,
                            message="Upload läuft",
                        )

                # Schnellvalidierung, damit kaputte Uploads nicht in der Liste landen
                with Image.open(tmp_path) as img:
                    img.verify()

                os.replace(tmp_path, final_path)
                ORIENTATION_CACHE.pop(filename, None)

                update_upload_status(active=False, phase="done", progress=100, filename=filename, message="Upload fertig")
                self.send_json({"ok": True, "filename": filename, "sizeBytes": length})
                return

            except Exception as e:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except:
                    pass
                update_upload_status(active=False, phase="error", message=f"Upload Fehler: {e}")
                self.send_json({"error": f"Upload fehlgeschlagen: {e}"}, status=500)
                return

        self.send_error(404, "Not found")


if __name__ == "__main__":
    print(f"🖼️  Muffi Frame Server auf Port {PORT}")
    print(f"📁  Fotos: {PHOTO_DIR}")
    print(f"⏱️  Refresh: {SERVER_CONFIG.get('refreshMs', DEFAULT_REFRESH_MS) // 1000}s")
    ThreadingHTTPServer(("0.0.0.0", PORT), FrameHandler).serve_forever()
