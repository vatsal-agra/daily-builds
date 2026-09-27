"""A stdlib-only HTTP server: serves the static grid UI and a small JSON
API backed directly by the real engine.Sheet — every value the browser
ever displays is something the Python engine actually computed, never a
JS reimplementation.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine import csvio, refs
from engine.sheet import Sheet

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def cell_payload(sheet, col, row):
    cell = sheet.get_cell(col, row)
    raw = cell.raw if cell else ""
    display = sheet.get_display(col, row)
    from engine import values as V
    is_error = cell is not None and V.is_error(cell.value)
    return {
        "addr": refs.col_to_letters(col) + str(row),
        "col": col,
        "row": row,
        "raw": raw,
        "display": display,
        "error": is_error,
    }


class AppState:
    def __init__(self):
        self.sheet = Sheet()
        self.lock = threading.RLock()


class Handler(BaseHTTPRequestHandler):
    server_version = "Recalc/1.0"

    # -- helpers ----------------------------------------------------------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, content_type="text/plain; charset=utf-8", status=200, headers=None):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):
        pass  # keep the demo's console output quiet

    # -- static files -------------------------------------------------------

    def _serve_static(self, path):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, name))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self._send_text("not found", status=404)
            return
        ext = os.path.splitext(full)[1]
        content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routing ------------------------------------------------------------

    def do_GET(self):
        try:
            self._do_GET()
        except (KeyError, ValueError, IndexError, TypeError) as e:
            self._send_json({"error": f"bad request: {e}"}, status=400)

    def do_POST(self):
        try:
            self._do_POST()
        except (KeyError, ValueError, IndexError, TypeError) as e:
            self._send_json({"error": f"bad request: {e}"}, status=400)

    def _do_GET(self):
        state = self.server.app_state
        if self.path == "/api/sheet":
            with state.lock:
                sheet = state.sheet
                max_col, max_row = sheet.used_bounds()
                cells = [cell_payload(sheet, c, r) for (c, r) in sheet.cells]
                self._send_json({
                    "cells": cells,
                    "bounds": [max_col, max_row],
                    "can_undo": sheet.can_undo(),
                    "can_redo": sheet.can_redo(),
                })
            return
        if self.path == "/api/export_csv":
            with state.lock:
                text = csvio.export_csv(state.sheet)
            self._send_text(text, content_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=recalc.csv"})
            return
        if self.path == "/api/save":
            with state.lock:
                text = csvio.save_workbook(state.sheet)
            self._send_text(text, content_type="application/json; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=workbook.json"})
            return
        self._serve_static(self.path)

    def _do_POST(self):
        state = self.server.app_state
        body = self._read_json()

        if self.path == "/api/cell":
            with state.lock:
                col, row, raw = int(body["col"]), int(body["row"]), body.get("raw", "")
                changed = state.sheet.set_cell(col, row, raw)
                self._respond_changed(state.sheet, changed)
            return

        if self.path == "/api/paste":
            with state.lock:
                src = body["src"]
                dest = body["dest"]
                changed = state.sheet.copy_paste((src[0], src[1]), (src[2], src[3]), (dest[0], dest[1]))
                self._respond_changed(state.sheet, changed)
            return

        if self.path == "/api/fill":
            with state.lock:
                sc, sr = body["src"]
                dest = body["dest"]
                changed = state.sheet.fill(sc, sr, (dest[0], dest[1]), (dest[2], dest[3]))
                self._respond_changed(state.sheet, changed)
            return

        if self.path == "/api/clear":
            with state.lock:
                rng = body["range"]
                changed = state.sheet.clear((rng[0], rng[1]), (rng[2], rng[3]))
                self._respond_changed(state.sheet, changed)
            return

        if self.path == "/api/undo":
            with state.lock:
                changed = state.sheet.undo()
                self._respond_changed(state.sheet, changed)
            return

        if self.path == "/api/redo":
            with state.lock:
                changed = state.sheet.redo()
                self._respond_changed(state.sheet, changed)
            return

        if self.path == "/api/import_csv":
            with state.lock:
                origin = body.get("origin", [1, 1])
                changed = csvio.import_csv(state.sheet, body.get("text", ""), origin=(origin[0], origin[1]))
                self._respond_changed(state.sheet, changed, full=True)
            return

        if self.path == "/api/load":
            with state.lock:
                try:
                    csvio.load_workbook(state.sheet, body.get("text", "{}"))
                except (json.JSONDecodeError, ValueError, KeyError):
                    self._send_json({"error": "invalid workbook file"}, status=400)
                    return
                self._respond_full(state.sheet)
            return

        if self.path == "/api/new":
            with state.lock:
                state.sheet = Sheet()
                self._respond_full(state.sheet)
            return

        self._send_json({"error": "not found"}, status=404)

    def _respond_changed(self, sheet, changed_keys, full=False):
        if full:
            self._respond_full(sheet)
            return
        cells = [cell_payload(sheet, c, r) for (c, r) in changed_keys]
        max_col, max_row = sheet.used_bounds()
        self._send_json({
            "cells": cells,
            "bounds": [max_col, max_row],
            "can_undo": sheet.can_undo(),
            "can_redo": sheet.can_redo(),
        })

    def _respond_full(self, sheet):
        max_col, max_row = sheet.used_bounds()
        cells = [cell_payload(sheet, c, r) for (c, r) in sheet.cells]
        self._send_json({
            "cells": cells,
            "bounds": [max_col, max_row],
            "can_undo": sheet.can_undo(),
            "can_redo": sheet.can_redo(),
            "full": True,
        })


def make_server(host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, port), Handler)
    server.app_state = AppState()
    return server


def serve(host="127.0.0.1", port=8765):
    server = make_server(host, port)
    print(f"Recalc serving on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
