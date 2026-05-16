#!/usr/bin/env python3
"""
Muffi Frame Server ❤️
Erkennt automatisch Hoch/Querformat und skaliert passend für ESP32-C6 Display
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageOps
import os, io, json

PHOTO_DIR  = "/mnt/muffi"
PORT       = 8765
DISPLAY_W  = 172   # Hochformat Breite
DISPLAY_H  = 320   # Hochformat Höhe

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
    offset_x = (target_w  - img.width)  // 2
    offset_y = (target_h - img.height) // 2
    canvas.paste(img, (offset_x, offset_y))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

class FrameHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[Frame] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        path = self.path.strip("/")

        # Dateiliste mit Orientierung
        if path == "" or path == "list":
            files = sorted([
                f for f in os.listdir(PHOTO_DIR)
                if f.lower().endswith((".jpg", ".jpeg", ".png"))
            ])
            file_info = []
            for f in files:
                fp = os.path.join(PHOTO_DIR, f)
                ori = get_orientation(fp)
                file_info.append({"name": f, "orientation": ori})

            data = json.dumps({
                "files": file_info,
                "latest": file_info[-1] if file_info else None,
                "count": len(file_info)
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data.encode())
            return

        # Einzelnes Bild (automatisch skaliert)
        filepath = os.path.join(PHOTO_DIR, path)
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

if __name__ == "__main__":
    print(f"🖼️  Muffi Frame Server auf Port {PORT}")
    print(f"📁  Fotos: {PHOTO_DIR}")
    HTTPServer(("0.0.0.0", PORT), FrameHandler).serve_forever()
