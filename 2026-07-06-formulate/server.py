"""HTTP JSON API + static file server for the Formulate spreadsheet UI.

The browser holds no formula logic at all: every edit is POSTed here, run
through the real Python engine, and the response tells the client exactly
which cells changed value.
"""

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from engine import csvio, persistence
from engine.errors import ErrorValue
from engine.workbook import Workbook, a1_to_ref, display_value, ref_to_a1

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_ROWS = 40
DEFAULT_COLS = 20


class AppState:
    def __init__(self, workbook=None, save_dir=None):
        self.workbook = workbook or _default_workbook()
        self.active_sheet = self.workbook.sheet_order[0]
        self.lock = threading.Lock()
        self.save_dir = Path(save_dir) if save_dir else Path(__file__).parent / "workbooks"
        self.save_dir.mkdir(exist_ok=True)


def _default_workbook():
    wb = Workbook()
    wb.add_sheet("Sheet1")
    return wb


def _cell_json(sheet, row, col):
    cell = sheet.cells.get((row, col))
    if cell is None:
        return None
    value = cell.computed
    error = value.code if isinstance(value, ErrorValue) else None
    json_value = None if error else value
    return {"raw": cell.raw, "value": json_value, "display": display_value(value), "error": error}


def state_payload(state, sheet_name):
    sheet_name = sheet_name or state.active_sheet
    sheet = state.workbook.get_or_create_sheet(sheet_name)
    used_r, used_c = sheet.used_bounds()
    rows = max(DEFAULT_ROWS, used_r + 2)
    cols = max(DEFAULT_COLS, used_c + 2)
    cells = {}
    for (r, c) in sheet.cells:
        cells[ref_to_a1(r, c)] = _cell_json(sheet, r, c)
    return {
        "sheets": list(state.workbook.sheet_order),
        "active": sheet_name,
        "rows": rows,
        "cols": cols,
        "cells": cells,
        "can_undo": bool(state.workbook.history),
        "can_redo": bool(state.workbook.future),
    }


def changed_payload(state, changed):
    out = {}
    for (sheet_name, row, col) in changed:
        sheet = state.workbook.sheets[sheet_name]
        out.setdefault(sheet_name, {})[ref_to_a1(row, col)] = _cell_json(sheet, row, col)
    return out


def _parse_ref_with_sheet(ref, default_sheet):
    if "!" in ref:
        sheet, cell = ref.split("!", 1)
        return sheet, cell
    return default_sheet, ref


def _range_to_bounds(sheet_name, range_text):
    default_sheet = sheet_name
    sheet_part, cell_part = _parse_ref_with_sheet(range_text, default_sheet)
    if ":" in cell_part:
        a, b = cell_part.split(":", 1)
    else:
        a = b = cell_part
    r1, c1 = a1_to_ref(a)
    r2, c2 = a1_to_ref(b)
    return sheet_part, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


class Handler(BaseHTTPRequestHandler):
    state: AppState = None  # set by make_server

    def log_message(self, fmt, *args):
        pass  # keep test/CI output quiet

    # -- helpers -------------------------------------------------------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
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
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            self.send_response(404)
            self.end_headers()
            return
        if not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- routing ---------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        state = self.state
        try:
            if parsed.path == "/api/state":
                sheet = qs.get("sheet", [None])[0]
                with state.lock:
                    self._send_json(state_payload(state, sheet))
                return
            if parsed.path == "/api/export_csv":
                sheet_name = qs.get("sheet", [state.active_sheet])[0]
                with state.lock:
                    sheet = state.workbook.get_or_create_sheet(sheet_name)
                    text = csvio.export_csv(sheet)
                self._send_text(text, content_type="text/csv; charset=utf-8")
                return
            if parsed.path == "/api/chart":
                sheet_name = qs.get("sheet", [state.active_sheet])[0]
                range_text = qs.get("range", [""])[0]
                with state.lock:
                    self._send_json(self._chart_data(state, sheet_name, range_text))
                return
            if parsed.path == "/api/list_workbooks":
                names = sorted(p.stem for p in state.save_dir.glob("*.json"))
                self._send_json({"names": names})
                return
            self._serve_static(parsed.path)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": str(e)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        state = self.state
        try:
            body = self._read_json()
            with state.lock:
                if parsed.path == "/api/edit":
                    self._handle_edit(state, body)
                elif parsed.path == "/api/undo":
                    changed = state.workbook.undo()
                    self._send_json(self._with_flags(state, {"changed": changed_payload(state, changed) if changed is not None else {}}))
                elif parsed.path == "/api/redo":
                    changed = state.workbook.redo()
                    self._send_json(self._with_flags(state, {"changed": changed_payload(state, changed) if changed is not None else {}}))
                elif parsed.path == "/api/autofill":
                    self._handle_autofill(state, body)
                elif parsed.path == "/api/import_csv":
                    self._handle_import_csv(state, body)
                elif parsed.path == "/api/sheet":
                    self._handle_sheet(state, body)
                elif parsed.path == "/api/save":
                    self._handle_save(state, body)
                elif parsed.path == "/api/load":
                    self._handle_load(state, body)
                else:
                    self._send_json({"error": "not found"}, status=404)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": str(e)}, status=500)

    # -- endpoint bodies ---------------------------------------------------

    def _with_flags(self, state, payload):
        payload["can_undo"] = bool(state.workbook.history)
        payload["can_redo"] = bool(state.workbook.future)
        return payload

    def _handle_edit(self, state, body):
        sheet_name = body.get("sheet") or state.active_sheet
        edits_in = body.get("edits")
        if edits_in is None:
            edits_in = [{"ref": body["ref"], "raw": body.get("raw")}]
        edits = [(sheet_name, *a1_to_ref(e["ref"]), e.get("raw")) for e in edits_in]
        changed = state.workbook.edit(edits)
        self._send_json(self._with_flags(state, {"changed": changed_payload(state, changed)}))

    def _handle_autofill(self, state, body):
        sheet_name = body.get("sheet") or state.active_sheet
        src_row, src_col = a1_to_ref(body["src"])
        edits = []
        for ref in body["targets"]:
            row, col = a1_to_ref(ref)
            raw = state.workbook.autofill(sheet_name, src_row, src_col, row, col)
            edits.append((sheet_name, row, col, raw))
        changed = state.workbook.edit(edits)
        self._send_json(self._with_flags(state, {"changed": changed_payload(state, changed)}))

    def _handle_import_csv(self, state, body):
        sheet_name = body.get("sheet") or state.active_sheet
        start_row, start_col = a1_to_ref(body.get("start") or "A1")
        edits = csvio.parse_csv_to_edits(sheet_name, body["text"], start_row, start_col)
        changed = state.workbook.edit(edits) if edits else {}
        self._send_json(self._with_flags(state, {"changed": changed_payload(state, changed)}))

    def _handle_sheet(self, state, body):
        action = body["action"]
        wb = state.workbook
        if action == "add":
            name = body["name"]
            if name in wb.sheets:
                self._send_json({"error": f"sheet {name!r} already exists"}, status=400)
                return
            wb.add_sheet(name)
            state.active_sheet = name
        elif action == "switch":
            if body["name"] not in wb.sheets:
                self._send_json({"error": "no such sheet"}, status=404)
                return
            state.active_sheet = body["name"]
        else:
            self._send_json({"error": "unknown action"}, status=400)
            return
        self._send_json({"sheets": list(wb.sheet_order), "active": state.active_sheet})

    def _handle_save(self, state, body):
        name = _safe_name(body.get("name") or "workbook")
        path = state.save_dir / f"{name}.json"
        path.write_text(persistence.to_json(state.workbook))
        self._send_json({"ok": True, "name": name})

    def _handle_load(self, state, body):
        name = _safe_name(body.get("name") or "workbook")
        path = state.save_dir / f"{name}.json"
        if not path.is_file():
            self._send_json({"error": "no such workbook"}, status=404)
            return
        state.workbook = persistence.from_json(path.read_text())
        state.active_sheet = state.workbook.sheet_order[0]
        self._send_json({"ok": True, "state": state_payload(state, state.active_sheet)})

    def _chart_data(self, state, sheet_name, range_text):
        sheet_part, r1, c1, r2, c2 = _range_to_bounds(sheet_name, range_text)
        sheet = state.workbook.get_or_create_sheet(sheet_part)
        rows = []
        for r in range(r1, r2 + 1):
            rows.append([sheet.get_computed(r, c) for c in range(c1, c2 + 1)])
        ncols = c2 - c1 + 1
        if ncols == 1:
            labels = [str(r - r1 + 1) for r in range(r1, r2 + 1)]
            series = [{"name": "value", "values": [_num_or_zero(v[0]) for v in rows]}]
        else:
            labels = [display_value(row[0]) for row in rows]
            series = []
            for col_idx in range(1, ncols):
                series.append({
                    "name": f"col{col_idx + 1}",
                    "values": [_num_or_zero(row[col_idx]) for row in rows],
                })
        return {"labels": labels, "series": series}


def _num_or_zero(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return 0.0


def _safe_name(name):
    keep = [c for c in name if c.isalnum() or c in "-_"]
    cleaned = "".join(keep) or "workbook"
    return cleaned[:64]


def make_server(state, host="127.0.0.1", port=8000):
    handler_cls = type("BoundHandler", (Handler,), {"state": state})
    return ThreadingHTTPServer((host, port), handler_cls)


def run(workbook=None, host="127.0.0.1", port=8000):
    state = AppState(workbook)
    server = make_server(state, host, port)
    print(f"Formulate serving on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
