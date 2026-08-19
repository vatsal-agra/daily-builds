"""Server-backed interactive Skein playground.

Same architecture this repo has used before (Gambit, Formulate, Unify):
the browser holds **zero** CRDT logic. Every keystroke becomes an HTTP
call; the server runs the real `Simulation`/`SimNetwork`/`RGA` code from
`skein/`, and the browser just polls and renders whatever the server
computes. A background thread keeps ticking the simulated network on a
fixed clock so messages actually arrive with visible latency even if
nobody's clicking anything — that's what makes the "watch it converge"
part of the demo real rather than instantaneous.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..simulate import Simulation

SITE_IDS = ["Alice", "Bob", "Carol"]
TICK_INTERVAL = 0.15  # seconds between automatic network ticks
LOG_MAXLEN = 60

_INDEX_HTML_PATH = Path(__file__).parent / "index.html"


class PlaygroundState:
    """All shared, mutable server state, behind one lock. A demo-scale
    toy — a real system would shard this per document — but correct and
    simple, which is what this project is optimizing to show."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sim: Simulation = None  # type: ignore[assignment]
        self.event_log: deque = deque(maxlen=LOG_MAXLEN)
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.sim = Simulation(SITE_IDS, seed=int(time.time() * 1000) & 0xFFFFFFFF, drop_prob=0.0, dup_prob=0.0)
            self.event_log.clear()
            self._log("session reset")

    def _log(self, msg: str) -> None:
        self.event_log.append({"tick": self.sim.network.tick_no, "msg": msg})

    # -- mutating operations, each logged -------------------------------------

    def do_type(self, site: str, pos: int, text: str) -> None:
        with self.lock:
            self.sim.type_str(site, pos, text)
            self._log(f"{site} typed {text!r} at {pos}")

    def do_delete(self, site: str, pos: int, count: int) -> None:
        with self.lock:
            self.sim.delete_range(site, pos, count)
            self._log(f"{site} deleted {count} char(s) at {pos}")

    def do_undo(self, site: str) -> None:
        with self.lock:
            op = self.sim.undo(site)
            self._log(f"{site} undo" + (" (nothing to undo)" if op is None else ""))

    def do_redo(self, site: str) -> None:
        with self.lock:
            op = self.sim.redo(site)
            self._log(f"{site} redo" + (" (nothing to redo)" if op is None else ""))

    def do_partition(self, site: str) -> None:
        with self.lock:
            self.sim.partition(site)
            self._log(f"⚡ network PARTITIONS {site}")

    def do_heal(self, site: str) -> None:
        with self.lock:
            self.sim.heal(site)
            self._log(f"✓ network HEALS {site} (anti-entropy resync)")

    def set_chaos(self, drop: float, dup: float, latency_min: int, latency_max: int) -> None:
        with self.lock:
            self.sim.network.drop_prob = max(0.0, min(1.0, drop))
            self.sim.network.dup_prob = max(0.0, min(1.0, dup))
            latency_min = max(0, int(latency_min))
            latency_max = max(latency_min, int(latency_max))
            self.sim.network.latency_range = (latency_min, latency_max)
            self._log(f"chaos knobs set: drop={self.sim.network.drop_prob:.2f} dup={self.sim.network.dup_prob:.2f} latency={self.sim.network.latency_range}")

    def tick(self) -> None:
        with self.lock:
            self.sim.step()

    def snapshot(self) -> dict:
        with self.lock:
            sim = self.sim
            return {
                "sites": {
                    sid: {
                        "text": site.text,
                        "can_undo": site.can_undo(),
                        "can_redo": site.can_redo(),
                        "partitioned": sim.network.is_partitioned(sid),
                        "pending": site.has_pending(),
                    }
                    for sid, site in sim.sites.items()
                },
                "network": {
                    "tick": sim.network.tick_no,
                    "in_flight": sim.network.in_flight_count(),
                    "stats": dict(sim.network.stats),
                    "drop_prob": sim.network.drop_prob,
                    "dup_prob": sim.network.dup_prob,
                    "latency_range": list(sim.network.latency_range),
                },
                "converged": sim.converged(),
                "log": list(self.event_log)[::-1],
            }


STATE = PlaygroundState()


def _ticker() -> None:
    while True:
        time.sleep(TICK_INTERVAL)
        STATE.tick()


class Handler(BaseHTTPRequestHandler):
    server_version = "Skein/0.1"

    def log_message(self, fmt, *args):  # pragma: no cover - quiet the default access log
        pass

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def do_GET(self):  # noqa: N802 - http.server's naming convention
        if self.path in ("/", "/index.html"):
            self._send_html(_INDEX_HTML_PATH.read_text(encoding="utf-8"))
        elif self.path == "/api/state":
            self._send_json(STATE.snapshot())
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        try:
            body = self._read_json()
            if self.path == "/api/type":
                STATE.do_type(body["site"], int(body["pos"]), body["text"])
            elif self.path == "/api/delete":
                STATE.do_delete(body["site"], int(body["pos"]), int(body["count"]))
            elif self.path == "/api/undo":
                STATE.do_undo(body["site"])
            elif self.path == "/api/redo":
                STATE.do_redo(body["site"])
            elif self.path == "/api/partition":
                STATE.do_partition(body["site"])
            elif self.path == "/api/heal":
                STATE.do_heal(body["site"])
            elif self.path == "/api/chaos":
                STATE.set_chaos(
                    float(body.get("drop", 0.0)),
                    float(body.get("dup", 0.0)),
                    int(body.get("latency_min", 1)),
                    int(body.get("latency_max", 3)),
                )
            elif self.path == "/api/reset":
                STATE.reset()
            else:
                self._send_json({"error": "not found"}, status=404)
                return
            self._send_json(STATE.snapshot())
        except (KeyError, ValueError, IndexError, TypeError) as e:
            self._send_json({"error": str(e)}, status=400)


def serve(port: int = 8765) -> None:
    threading.Thread(target=_ticker, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Skein playground running at http://127.0.0.1:{port}/  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
