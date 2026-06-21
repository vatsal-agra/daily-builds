"""Progressive HTML viewer: renders tiles into a live-updating browser page.

Serves a page via stdlib http.server. As tiles complete they are base64-encoded
and sent to the browser via Server-Sent Events (SSE), where JavaScript paints
them onto a canvas element tile by tile.
"""
import base64
import io
import json
import math
import multiprocessing
import os
import random
import struct
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from .scene import load_scene
from .renderer import _init_worker, _render_tile
from .vec3 import Vec3
from .png_writer import _chunk, _PNG_SIGNATURE


# ---- tiny in-memory PNG for a single tile ----

def _tile_to_png_bytes(pixels, x0, y0, x1, y1):
    """Encode a tile (list of Vec3, row-major) as PNG bytes (in memory)."""
    w = x1 - x0
    h = y1 - y0
    raw = bytearray()
    idx = 0
    for row in range(h):
        raw.append(1)  # Sub filter
        pr, pg, pb = 0, 0, 0
        for col in range(w):
            r, g, b = pixels[idx].to_rgb8()
            raw.append((r - pr) & 0xFF)
            raw.append((g - pg) & 0xFF)
            raw.append((b - pb) & 0xFF)
            pr, pg, pb = r, g, b
            idx += 1
    compressed = zlib.compress(bytes(raw), level=1)  # fast compress for live view
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    data = (
        _PNG_SIGNATURE
        + _chunk(b'IHDR', ihdr_data)
        + _chunk(b'IDAT', compressed)
        + _chunk(b'IEND', b'')
    )
    return data


# ---- HTML page ----

def _make_html(width, height, host, port):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pathtracer — Live Preview</title>
<style>
  body {{ background:#111; color:#eee; font-family:monospace; margin:0; padding:16px; }}
  h1   {{ font-size:14px; color:#7af; margin:0 0 8px; }}
  #status {{ font-size:12px; color:#fa7; margin:4px 0 8px; }}
  canvas {{ display:block; border:1px solid #333; image-rendering:pixelated; max-width:100%; }}
</style>
</head>
<body>
<h1>Pathtracer — Progressive Render</h1>
<div id="status">Connecting…</div>
<canvas id="c" width="{width}" height="{height}"></canvas>
<script>
const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
const status = document.getElementById('status');
const t0     = Date.now();

const es = new EventSource('/events');
let done = 0, total = 0;

es.addEventListener('meta', e => {{
  const d = JSON.parse(e.data);
  total = d.total_tiles;
  status.textContent = 'Rendering ' + d.width + '×' + d.height + ' @ ' + d.spp + ' SPP …';
}});

es.addEventListener('tile', e => {{
  const d    = JSON.parse(e.data);
  const img  = new Image();
  img.onload = () => {{
    ctx.drawImage(img, d.x0, d.y0);
    done++;
    const pct  = (done / total * 100).toFixed(1);
    const secs = ((Date.now() - t0) / 1000).toFixed(1);
    status.textContent = pct + '% — ' + done + '/' + total + ' tiles — ' + secs + 's';
    if (done === total) {{
      status.textContent = '✓ Done — ' + d.width + '×' + d.height + ' in ' + secs + 's';
      es.close();
    }}
  }};
  img.src = 'data:image/png;base64,' + d.png_b64;
}});

es.onerror = () => {{
  if (done === total && total > 0) return;
  status.textContent = 'Connection closed.';
}};
</script>
</body>
</html>
"""


# ---- HTTP server ----

_viewer_state = {}   # shared dict pushed to by renderer thread


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            html = _make_html(
                _viewer_state['width'], _viewer_state['height'],
                _viewer_state['host'], _viewer_state['port'],
            ).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(html))
            self.end_headers()
            self.wfile.write(html)

        elif path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()

            # Send meta event
            meta = json.dumps({
                'width': _viewer_state['width'],
                'height': _viewer_state['height'],
                'spp': _viewer_state['spp'],
                'total_tiles': _viewer_state['total_tiles'],
            })
            try:
                self.wfile.write(f'event:meta\ndata:{meta}\n\n'.encode())
                self.wfile.flush()
            except BrokenPipeError:
                return

            # Stream tiles as they arrive
            sent_idx = 0
            while True:
                tiles = _viewer_state.get('completed_tiles', [])
                while sent_idx < len(tiles):
                    td = tiles[sent_idx]
                    payload = json.dumps(td)
                    try:
                        self.wfile.write(f'event:tile\ndata:{payload}\n\n'.encode())
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    sent_idx += 1
                if _viewer_state.get('done') and sent_idx >= len(tiles):
                    break
                time.sleep(0.05)
        else:
            self.send_response(404)
            self.end_headers()


def view(scene, workers=None, tile_size=16, host='127.0.0.1', port=8080):
    """Render `scene` progressively and serve a live-update browser page.

    Opens http://{host}:{port}/ — navigate there while render runs.
    Blocks until the render is complete, then keeps the server alive until
    Ctrl-C so you can view the final image.
    """
    width   = scene.width
    height  = scene.height
    spp     = scene.spp
    max_depth = scene.max_depth

    if workers is None:
        workers = max(1, multiprocessing.cpu_count())

    # Build tile list
    tiles = []
    seed = 0
    for y0 in range(0, height, tile_size):
        for x0 in range(0, width, tile_size):
            x1 = min(x0 + tile_size, width)
            y1 = min(y0 + tile_size, height)
            tiles.append((x0, y0, x1, y1, width, height, spp, max_depth, seed))
            seed += 1

    _viewer_state.clear()
    _viewer_state.update({
        'width': width, 'height': height, 'spp': spp,
        'total_tiles': len(tiles),
        'host': host, 'port': port,
        'completed_tiles': [],
        'done': False,
    })

    # Start HTTP server in a daemon thread
    server = HTTPServer((host, port), _Handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()
    print(f"  Browser: http://{host}:{port}/")

    # Render tiles and push to shared state
    def do_render():
        if workers == 1:
            _init_worker(scene.world, scene.camera, scene.background)
            for tile_args in tiles:
                x0, y0, x1, y1, pixels = _render_tile(tile_args)
                png_bytes = _tile_to_png_bytes(pixels, x0, y0, x1, y1)
                _viewer_state['completed_tiles'].append({
                    'x0': x0, 'y0': y0,
                    'width': scene.width, 'height': scene.height,
                    'png_b64': base64.b64encode(png_bytes).decode(),
                })
        else:
            ctx = multiprocessing.get_context('fork')
            with ctx.Pool(
                processes=workers,
                initializer=_init_worker,
                initargs=(scene.world, scene.camera, scene.background),
            ) as pool:
                for x0, y0, x1, y1, pixels in pool.imap_unordered(_render_tile, tiles):
                    png_bytes = _tile_to_png_bytes(pixels, x0, y0, x1, y1)
                    _viewer_state['completed_tiles'].append({
                        'x0': x0, 'y0': y0,
                        'width': scene.width, 'height': scene.height,
                        'png_b64': base64.b64encode(png_bytes).decode(),
                    })
        _viewer_state['done'] = True

    render_thread = threading.Thread(target=do_render)
    render_thread.start()
    render_thread.join()

    print("  Render complete. Press Ctrl-C to stop the server.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
