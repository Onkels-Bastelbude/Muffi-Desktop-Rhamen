#!/usr/bin/env python3
"""
Muffi Frame Server ❤️
Erkennt automatisch Hoch/Querformat und skaliert passend für ESP32-C6 Display
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageOps
from urllib.parse import unquote, quote, parse_qs
from html import escape
import os, io, json

PHOTO_DIR  = "/mnt/muffi"
PORT       = 8765
DISPLAY_W  = 172   # Hochformat Breite
DISPLAY_H  = 320   # Hochformat Höhe

CONFIG_PATH = "/home/maika/.frame-server-config.json"
DEFAULT_REFRESH_MS = 5 * 60 * 1000
MIN_REFRESH_MS = 10 * 1000
MAX_REFRESH_MS = 24 * 60 * 60 * 1000


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


def load_config():
    cfg = {"refreshMs": DEFAULT_REFRESH_MS}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            disk = json.load(f)
            cfg["refreshMs"] = clamp_refresh_ms(disk.get("refreshMs", DEFAULT_REFRESH_MS))
    except:
        pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    payload = {
        "refreshMs": clamp_refresh_ms(cfg.get("refreshMs", DEFAULT_REFRESH_MS))
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


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

    file_info = []
    for f in files:
        fp = os.path.join(PHOTO_DIR, f)
        ori = get_orientation(fp)
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
        latest = file_info[-1] if file_info else None
        latest_html = "<p>Kein Bild gefunden.</p>"
        if latest:
            latest_html = (
                f'<img src="/{quote(latest["name"])}" alt="latest" style="max-width:100%;border-radius:12px;border:1px solid #ddd;" />'
                f'<p><b>{escape(latest["name"])}</b> · {latest["orientation"]}</p>'
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
    input {{ font-size: 16px; padding: 8px; width: 130px; }}
    button {{ font-size: 16px; padding: 8px 12px; cursor: pointer; }}
    #cfg-msg {{ font-size: 14px; color: #444; margin-top: 6px; min-height: 1.2em; }}
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
    <h2>Automatische Abfrage (ESP)</h2>
    <p>Aktuell: <b><span id="current-seconds">{refresh_seconds}</span> Sekunden</b></p>
    <form id="cfg-form" class="row">
      <label for="refreshSeconds">Intervall (Sekunden):</label>
      <input id="refreshSeconds" name="refreshSeconds" type="number" min="10" max="86400" value="{refresh_seconds}" required />
      <button type="submit">Speichern</button>
    </form>
    <div id="cfg-msg"></div>
  </div>

  <div class="card">
    <h2>Neuestes Bild</h2>
    {latest_html}
  </div>

  <script>
    const form = document.getElementById('cfg-form');
    const msg = document.getElementById('cfg-msg');
    const current = document.getElementById('current-seconds');

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
    a {{ text-decoration: none; }}
  </style>
</head>
<body>
  <h1>📚 Muffi Galerie</h1>
  <p><a href="/">⬅ Zurück zum Dashboard</a></p>
  <div class="grid">{gallery}</div>
</body>
</html>"""

    def do_GET(self):
        raw_path = self.path.split("?", 1)[0]
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

        # Dateiliste: /list bleibt schlank für ESP, /api/list ist voll für Web/Tools
        if path == "list":
            esp_files = [{"name": f["name"], "orientation": f["orientation"]} for f in file_info]
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
        raw_path = self.path.split("?", 1)[0]
        path = unquote(raw_path.strip("/"))

        if path != "api/config":
            self.send_error(404, "Not found")
            return

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


if __name__ == "__main__":
    print(f"🖼️  Muffi Frame Server auf Port {PORT}")
    print(f"📁  Fotos: {PHOTO_DIR}")
    print(f"⏱️  Refresh: {SERVER_CONFIG.get('refreshMs', DEFAULT_REFRESH_MS) // 1000}s")
    HTTPServer(("0.0.0.0", PORT), FrameHandler).serve_forever()
