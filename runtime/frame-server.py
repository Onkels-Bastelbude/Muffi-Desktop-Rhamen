#!/usr/bin/env python3
"""
Muffi Frame Server ❤️
Erkennt automatisch Hoch/Querformat und skaliert passend für ESP32-C6 Display
"""

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageOps
from urllib.parse import unquote, quote, parse_qs, urlparse
from html import escape
import os, io, json, time, threading, re

PHOTO_DIR  = "/mnt/muffi"
PORT       = 8765
DISPLAY_W  = 172   # Hochformat Breite
DISPLAY_H  = 320   # Hochformat Höhe

CONFIG_PATH = "/home/maika/.frame-server-config.json"
DEFAULT_REFRESH_MS = 5 * 60 * 1000
MIN_REFRESH_MS = 10 * 1000
MAX_REFRESH_MS = 24 * 60 * 60 * 1000
MAX_UPLOAD_BYTES = 30 * 1024 * 1024

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


def load_config():
    cfg = {
        "refreshMs": DEFAULT_REFRESH_MS,
        "led": sanitize_led_config({}),
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            disk = json.load(f)
            cfg["refreshMs"] = clamp_refresh_ms(disk.get("refreshMs", DEFAULT_REFRESH_MS))
            cfg["led"] = sanitize_led_config(disk.get("led", {}))
    except:
        pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    payload = {
        "refreshMs": clamp_refresh_ms(cfg.get("refreshMs", DEFAULT_REFRESH_MS)),
        "led": sanitize_led_config(cfg.get("led", {})),
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
        photo_root = os.path.abspath(PHOTO_DIR)
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


def update_led_config(patch: dict):
    with LED_LOCK:
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
    if not os.path.isdir(PHOTO_DIR):
        return []

    files = sorted([
        f for f in os.listdir(PHOTO_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])

    # Cache aufräumen (gelöschte Dateien entfernen)
    existing = set(files)
    for k in list(ORIENTATION_CACHE.keys()):
        if k not in existing:
            ORIENTATION_CACHE.pop(k, None)

    file_info = []
    # Pro Request nur begrenzt neue Orientierungen scannen, damit /list schnell bleibt
    scan_budget = 8
    for f in files:
        fp = os.path.join(PHOTO_DIR, f)
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

        photo_dir_ok = os.path.isdir(PHOTO_DIR)
        mount_ok = os.path.ismount(PHOTO_DIR)
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
    <p>Foto-Ordner: <code>{escape(PHOTO_DIR)}</code></p>
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
        file_info = list_photos()

        # Dashboard + Galerie
        if path in ("", "index.html"):
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

        if path == "api/upload-status":
            self.send_json(get_upload_status_snapshot())
            return

        if path == "api/frame-state":
            self.send_json(get_frame_state_snapshot())
            return

        if path == "api/led":
            self.send_json(get_led_config_snapshot())
            return

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
        photo_root = os.path.abspath(PHOTO_DIR)
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

            SERVER_CONFIG["refreshMs"] = clamp_refresh_ms(refresh_ms)
            try:
                save_config(SERVER_CONFIG)
            except Exception as e:
                self.send_json({"error": f"Speichern fehlgeschlagen: {e}"}, status=500)
                return

            self.send_json({
                "ok": True,
                "refreshMs": SERVER_CONFIG["refreshMs"],
                "refreshSeconds": SERVER_CONFIG["refreshMs"] // 1000
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

            photo_root = os.path.abspath(PHOTO_DIR)
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
            if not os.path.isdir(PHOTO_DIR):
                self.send_json({"error": "Foto-Ordner nicht verfügbar"}, status=503)
                return

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

            photo_root = os.path.abspath(PHOTO_DIR)
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
