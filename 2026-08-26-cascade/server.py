#!/usr/bin/env python3
"""Cascade playground server — a stdlib `http.server`, no dependencies.

Serves `playground.html` (a thin client with zero layout logic) and a
`POST /render` endpoint that runs the *real* Cascade engine on whatever
HTML/CSS the browser sends and returns the rendered SVG plus a flattened
box-model list (content/padding/border/margin rects per element) for the
client's hover-to-inspect overlay — same "server does the real work, the
browser just displays it" pattern this repo's history already used for
Gambit's chess board, Formulate's spreadsheet, and Trove's search UI.

Run:  python3 server.py [port]   (defaults to 8420)
"""
import http.server
import json
import os
import socketserver
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cascade.engine import render_html  # noqa: E402
from cascade.dom import Element  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_HTML = """<div class="card">
  <h2>Cascade Playground</h2>
  <p>Edit the HTML/CSS on the left and hit <b>Render</b>. Hover any box
  in the preview to see its margin / border / padding / content edges —
  this is the <i>real</i> layout engine, not a mock.</p>
  <span class="tag">html</span><span class="tag">css</span><span class="tag">layout</span>
</div>
<div class="float-box"></div>
<p class="wrap-text">This paragraph wraps around the floated box on the
left, driven entirely by cascade/layout.py's float placement algorithm.</p>
"""

DEFAULT_CSS = """body { font-family: sans-serif; margin: 16px; }
.card { width: 420px; padding: 16px; border: 3px solid #333;
        background: #f3f3f3; margin-bottom: 16px; }
.card h2 { margin-top: 0; }
.tag { display: inline-block; background: #4477cc; color: white;
       padding: 3px 8px; margin-right: 4px; }
.float-box { width: 90px; height: 70px; float: left; background: #cc4444;
             margin: 0 12px 12px 0; }
.wrap-text { font-family: monospace; }
"""


def flatten_boxes(root_box):
    out = []
    if root_box is None:
        return out
    for b in root_box.walk():
        if not isinstance(b.node, Element):
            continue
        d = b.dims
        out.append({
            "tag": b.node.tag,
            "id": b.node.id(),
            "content": _rect(d.content),
            "padding": _rect(d.padding_box()),
            "border": _rect(d.border_box()),
            "margin": _rect(d.margin_box()),
        })
    return out


def _rect(r):
    return {"x": round(r.x, 1), "y": round(r.y, 1), "width": round(r.width, 1), "height": round(r.height, 1)}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout quiet; errors still raise

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/playground.html"):
            path = os.path.join(HERE, "playground.html")
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self.send_error(404, "playground.html not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/default":
            self._send_json({"html": DEFAULT_HTML, "css": DEFAULT_CSS})
        else:
            self.send_error(404, "not found")

    def do_POST(self):
        if self.path != "/render":
            self.send_error(404, "not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON request body"}, status=400)
            return
        html = payload.get("html", "")
        css = payload.get("css", "")
        width = int(payload.get("width", 700))
        try:
            result = render_html(html, extra_css=css, viewport_width=width)
        except Exception as e:  # never let a bad user page 500 the server
            self._send_json({"error": f"{type(e).__name__}: {e}"}, status=200)
            return
        self._send_json({
            "svg": result.svg,
            "boxes": flatten_boxes(result.box),
        })


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8420
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"Cascade playground: http://127.0.0.1:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
