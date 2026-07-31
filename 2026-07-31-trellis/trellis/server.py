"""Stdlib-only HTTP server exposing a JSON API over a Workbook, plus static
file serving for the browser UI in web/. The browser holds zero formula or
recalculation logic -- every edit is a real HTTP round trip that goes
through the same parser/evaluator/dependency-graph engine the CLI and test
suite use."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .addr import index_to_col
from .errors import TrellisError
from .sheet import Workbook
from .csvio import export_csv, import_csv
from .history import History
from .chart import render_chart_svg

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

DEFAULT_ROWS = 40
DEFAULT_COLS = 18


def _cell_json(cell):
    if cell is None or cell.raw is None:
        return {"raw": None, "display": "", "error": None, "is_formula": False}
    val = cell.value
    if isinstance(val, TrellisError):
        return {"raw": cell.raw, "display": val.code, "error": val.code, "is_formula": cell.is_formula}
    from .functions import to_display_str
    return {
        "raw": cell.raw,
        "display": to_display_str(val),
        "error": None,
        "is_formula": cell.is_formula,
    }


class AppState:
    def __init__(self, rows=DEFAULT_ROWS, cols=DEFAULT_COLS):
        self.wb = Workbook()
        self.history = History(self.wb)
        self.rows = rows
        self.cols = cols
        self.lock = threading.RLock()

    def sheet_snapshot(self, sheet_name):
        sheet = self.wb.sheets[sheet_name]
        cells = {}
        for r in range(1, self.rows + 1):
            for c in range(1, self.cols + 1):
                cell = sheet.get(r, c)
                if cell is not None and cell.raw is not None:
                    cells[f"{r},{c}"] = _cell_json(cell)
        return {
            "sheet": sheet_name,
            "sheets": list(self.wb.sheets.keys()),
            "rows": self.rows,
            "cols": self.cols,
            "col_labels": [index_to_col(c) for c in range(1, self.cols + 1)],
            "cells": cells,
            "can_undo": self.history.can_undo(),
            "can_redo": self.history.can_redo(),
        }

    def changed_snapshot(self, sheet_name, changed_keys):
        out = {}
        for (s, r, c) in changed_keys:
            if s != sheet_name:
                continue
            cell = self.wb.sheets[s].get(r, c)
            out[f"{r},{c}"] = _cell_json(cell)
        return out


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Trellis/1.0"

        def log_message(self, fmt, *args):
            pass  # keep test/demo output quiet; errors still raised normally

        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text, status=200, content_type="text/plain; charset=utf-8"):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                return self._serve_static("index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                return self._serve_static(rel)

            if path == "/api/state":
                with state.lock:
                    sheet_name = qs.get("sheet", [state.wb.active_sheet])[0]
                    if sheet_name not in state.wb.sheets:
                        return self._send_json({"error": "no such sheet"}, 404)
                    return self._send_json(state.sheet_snapshot(sheet_name))

            if path == "/api/export.csv":
                with state.lock:
                    sheet_name = qs.get("sheet", [state.wb.active_sheet])[0]
                    if sheet_name not in state.wb.sheets:
                        return self._send_json({"error": "no such sheet"}, 404)
                    csv_text = export_csv(state.wb.sheets[sheet_name])
                    return self._send_text(csv_text, content_type="text/csv; charset=utf-8")

            if path == "/api/chart":
                with state.lock:
                    sheet_name = qs.get("sheet", [state.wb.active_sheet])[0]
                    rng = qs.get("range", [""])[0]
                    kind = qs.get("kind", ["bar"])[0]
                    if sheet_name not in state.wb.sheets:
                        return self._send_json({"error": "no such sheet"}, 404)
                    try:
                        svg = render_chart_svg(state.wb, sheet_name, rng, kind)
                    except ValueError as e:
                        return self._send_json({"error": str(e)}, 400)
                    return self._send_text(svg, content_type="image/svg+xml")

            return self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            payload = self._read_json()
            if payload is None:
                return self._send_json({"error": "invalid JSON body"}, 400)

            if path == "/api/cell":
                return self._handle_set_cell(payload)
            if path == "/api/undo":
                return self._handle_history(payload, "undo")
            if path == "/api/redo":
                return self._handle_history(payload, "redo")
            if path == "/api/sheet":
                return self._handle_add_sheet(payload)
            if path == "/api/import.csv":
                return self._handle_import_csv(payload)

            return self._send_json({"error": "not found"}, 404)

        def _handle_set_cell(self, payload):
            try:
                sheet_name = payload["sheet"]
                row = int(payload["row"])
                col = int(payload["col"])
                raw = payload.get("raw")
            except (KeyError, TypeError, ValueError):
                return self._send_json({"error": "expected sheet/row/col/raw"}, 400)
            with state.lock:
                if sheet_name not in state.wb.sheets:
                    return self._send_json({"error": "no such sheet"}, 404)
                if row < 1 or col < 1 or row > state.rows or col > state.cols:
                    return self._send_json({"error": "cell out of range"}, 400)
                state.history.set_cell(sheet_name, row, col, raw)
                changed = state.history.last_changed
                return self._send_json({
                    "changed": state.changed_snapshot(sheet_name, changed),
                    "can_undo": state.history.can_undo(),
                    "can_redo": state.history.can_redo(),
                })

        def _handle_history(self, payload, direction):
            with state.lock:
                sheet_name = payload.get("sheet", state.wb.active_sheet)
                fn = state.history.undo if direction == "undo" else state.history.redo
                changed = fn()
                if changed is None:
                    return self._send_json({"error": f"nothing to {direction}"}, 400)
                return self._send_json({
                    "changed": state.changed_snapshot(sheet_name, changed),
                    "can_undo": state.history.can_undo(),
                    "can_redo": state.history.can_redo(),
                })

        def _handle_add_sheet(self, payload):
            name = (payload.get("name") or "").strip()
            if not name:
                return self._send_json({"error": "sheet name required"}, 400)
            with state.lock:
                if name in state.wb.sheets:
                    return self._send_json({"error": "sheet already exists"}, 400)
                state.wb.add_sheet(name)
                state.wb.active_sheet = name
                return self._send_json(state.sheet_snapshot(name))

        def _handle_import_csv(self, payload):
            sheet_name = payload.get("sheet", state.wb.active_sheet)
            text = payload.get("text", "")
            with state.lock:
                if sheet_name not in state.wb.sheets:
                    return self._send_json({"error": "no such sheet"}, 404)
                import_csv(state.wb, sheet_name, text)
                state.history.clear()
                return self._send_json(state.sheet_snapshot(sheet_name))

        def _serve_static(self, rel_path, content_type=None):
            safe = os.path.normpath(rel_path).lstrip(os.sep)
            if safe.startswith(".."):
                return self._send_json({"error": "not found"}, 404)
            full = os.path.join(WEB_DIR, safe)
            if not os.path.isfile(full):
                return self._send_json({"error": "not found"}, 404)
            with open(full, "rb") as f:
                body = f.read()
            if content_type is None:
                content_type = {
                    ".js": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".html": "text/html; charset=utf-8",
                }.get(os.path.splitext(full)[1], "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def make_server(host="127.0.0.1", port=8765, rows=DEFAULT_ROWS, cols=DEFAULT_COLS):
    state = AppState(rows=rows, cols=cols)
    handler = make_handler(state)
    httpd = ThreadingHTTPServer((host, port), handler)
    return httpd, state


def serve(host="127.0.0.1", port=8765):
    httpd, _state = make_server(host, port)
    print(f"Trellis serving on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
