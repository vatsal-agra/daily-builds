"""Stdlib-only HTTP backend for the interactive browser UI.

Same pattern as this repo's earlier server-backed apps (Gambit's chess
board, Formulate's spreadsheet): the browser holds *zero* circuit-solving
logic. Every "Simulate" click is a real JSON round trip into this process,
which parses the submitted netlist and runs the actual MNA/Newton-Raphson/
backward-Euler engine — the exact same code path as the CLI.
"""

import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ac as ac_mod
from . import circuits, dc, netlist, transient
from .linalg import SingularMatrixError
from .mna import Circuit

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_KNOWN_ERRORS = (ValueError, SingularMatrixError, dc.ConvergenceError, KeyError)


def _circuit_from_netlist(text):
    elements, directives = netlist.parse_netlist(text)
    if not elements:
        raise ValueError("netlist has no elements")
    return Circuit(elements, name="session")


def _run_dc(circuit, params):
    voltages, currents = dc.operating_point(circuit)
    return {"type": "dc", "voltages": voltages, "currents": currents}


def _run_tran(circuit, params):
    t_stop = float(params["tstop"])
    dt = float(params["dt"])
    if t_stop <= 0 or dt <= 0:
        raise ValueError("tstop and dt must both be > 0")
    if t_stop / dt > 200_000:
        raise ValueError("that's more than 200,000 timesteps — increase dt or shrink tstop")
    result = transient.simulate(circuit, t_stop, dt, use_ic=bool(params.get("uic")))
    return {
        "type": "tran",
        "times": result.times,
        "voltages": result.voltages,
        "currents": result.currents,
    }


def _run_ac(circuit, params):
    f_start = float(params["fstart"])
    f_stop = float(params["fstop"])
    points = int(params.get("points", 50))
    scale = params.get("scale", "log")
    if points > 2000:
        raise ValueError("that's more than 2000 sweep points — reduce points")
    result = ac_mod.sweep(circuit, f_start, f_stop, points, scale)
    nodes = list(result.voltages)
    return {
        "type": "ac",
        "freqs": result.freqs,
        "magnitude": {n: result.magnitude(n) for n in nodes},
        "magnitude_db": {n: result.magnitude_db(n) for n in nodes},
        "phase": {n: result.phase_deg(n) for n in nodes},
    }


_ANALYSES = {"dc": _run_dc, "tran": _run_tran, "ac": _run_ac}


def _json_safe(obj):
    """Recursively replace non-finite floats (inf/-inf/nan) with None.

    `json.dumps` will happily emit the literal tokens Infinity/-Infinity/
    NaN, which are not legal JSON — a browser's JSON.parse throws on them.
    This is the last line of defense at the HTTP boundary (ac.py already
    floors dB values sanely; this catches anything else, e.g. a
    pathological user-supplied component value overflowing to inf).
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


class Handler(BaseHTTPRequestHandler):
    server_version = "Faraday/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet; errors still surface in HTTP responses

    def _send_json(self, obj, status=200):
        body = json.dumps(_json_safe(obj)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            data = path.read_bytes()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif self.path == "/api/presets":
            presets = {}
            for name, factory in circuits.PRESETS.items():
                c = factory()
                presets[name] = netlist.to_netlist(c.elements, title=name)
            self._send_json(presets)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/api/simulate":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 2_000_000:
            self._send_json({"error": "request body missing or too large"}, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            analysis = payload.get("analysis")
            if analysis not in _ANALYSES:
                raise ValueError(f"unknown analysis {analysis!r} (expected dc/tran/ac)")
            circuit = _circuit_from_netlist(payload.get("netlist", ""))
            result = _ANALYSES[analysis](circuit, payload)
            self._send_json(result)
        except _KNOWN_ERRORS as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:  # last-resort guard: never leak a raw traceback
            self._send_json({"error": f"internal error: {exc}"}, 500)


def serve(port=8765):
    addr = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(addr, Handler)
    print(f"Faraday running at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
