#!/usr/bin/env python3
"""The interactive visualizer's backend: stdlib `http.server` only, zero
client-side layout logic. Every request runs the real HTML/CSS text
through the actual Python engine and returns every pipeline stage --
the browser just displays what the server computed."""

import argparse
import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from reflow.browser import render_page
from reflow.visualize import dump_cascade_text, dump_cssom_text, layout_to_svg

VIEWER_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'viewer.html')


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            try:
                with open(VIEWER_HTML_PATH, 'rb') as f:
                    body = f.read()
            except OSError as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'viewer.html not found: {e}'.encode('utf-8'))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != '/render':
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8')) if raw else {}
            html_text = payload.get('html', '') or ''
            css_text = payload.get('css', '') or ''
            width = int(payload.get('width', 800) or 800)
            width = max(50, min(4000, width))

            result = render_page(html_text, extra_css=css_text, viewport_width=width)
            response = {
                'dom_text': result.dom.to_debug_string() or '(empty document)',
                'cssom_text': dump_cssom_text(result.stylesheet),
                'cascade_text': dump_cascade_text(result.dom, result.styles),
                'layout_svg': layout_to_svg(result.layout_root),
                'png_base64': base64.b64encode(result.png).decode('ascii'),
                'width': result.canvas.width,
                'height': result.canvas.height,
            }
            self._send_json(response)
        except Exception as e:  # noqa: BLE001 -- a bad request must not kill the server
            self._send_json({'error': f'{type(e).__name__}: {e}'}, status=400)

    def log_message(self, format_str, *args):
        sys.stderr.write('%s - %s\n' % (self.address_string(), format_str % args))


def main():
    parser = argparse.ArgumentParser(description='Reflow interactive visualizer server')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), Handler)
    print(f'Reflow visualizer: http://{args.host}:{args.port}/', file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
