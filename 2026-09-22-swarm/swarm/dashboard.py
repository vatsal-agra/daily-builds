"""A live swarm dashboard: every real Node (in whatever OS process it's
running as) fire-and-forget POSTs its own events to this hub, and the hub
re-broadcasts them to any browser watching over Server-Sent Events.

This deliberately plays NO role in how the swarm actually works -- peers
never talk to it, don't need it to be running, and a Node that can't reach
it just silently drops its event posts and keeps transferring pieces
exactly as if it were never configured. It exists purely so a human (or a
headless-browser test) can watch a real, genuinely decentralized,
multi-process swarm converge live, the same "server computes / browser
only renders" split this repo's other visualizers (Matchbook, Concord) use
-- except here "server computes" is however many independent swarm.Node
processes happen to be running, and the hub is just a dumb relay with no
opinion about protocol correctness.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

MAX_HISTORY = 500
SSE_QUEUE_MAXSIZE = 1000


def _page_html() -> bytes:
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "dashboard.html"), "rb") as f:
        return f.read()


class _Handler(BaseHTTPRequestHandler):
    server: "DashboardServer"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/" or self.path == "/index.html":
            body = _page_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/stream":
            self._handle_stream()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):  # noqa: N802
        if self.path != "/events":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        self.server.publish(evt)
        self.send_response(204)
        self.end_headers()

    def _handle_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        client_queue: "queue.Queue" = queue.Queue(maxsize=SSE_QUEUE_MAXSIZE)
        self.server.add_client(client_queue)
        try:
            for evt in self.server.history_snapshot():
                self._write_event(evt)
            while True:
                evt = client_queue.get()
                self._write_event(evt)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.remove_client(client_queue)

    def _write_event(self, evt: dict) -> None:
        self.wfile.write(f"data: {json.dumps(evt)}\n\n".encode())
        self.wfile.flush()


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int):
        super().__init__((host, port), _Handler)
        self._lock = threading.Lock()
        self._clients: list = []
        self._history: list = []

    def publish(self, evt: dict) -> None:
        with self._lock:
            self._history.append(evt)
            if len(self._history) > MAX_HISTORY:
                self._history.pop(0)
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(evt)
            except queue.Full:
                pass  # a slow/stuck browser tab shouldn't block the swarm's event flow

    def add_client(self, q) -> None:
        with self._lock:
            self._clients.append(q)

    def remove_client(self, q) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def history_snapshot(self) -> list:
        with self._lock:
            return list(self._history)


def run_dashboard(host: str = "127.0.0.1", port: int = 0) -> DashboardServer:
    server = DashboardServer(host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._thread = thread  # type: ignore[attr-defined]
    return server


class EventReporter:
    """Runs in a Node's own process: queues events off the hot path and
    POSTs them to the dashboard hub from a single background thread, so a
    slow or unreachable dashboard can never add latency to real transfers."""

    def __init__(self, dashboard_url: str, timeout: float = 2.0):
        self.url = dashboard_url.rstrip("/") + "/events"
        self.timeout = timeout
        self._q: "queue.Queue[Optional[dict]]" = queue.Queue(maxsize=2000)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def report(self, evt: dict) -> None:
        try:
            self._q.put_nowait(evt)
        except queue.Full:
            pass  # drop rather than block the caller

    def _run(self) -> None:
        while True:
            evt = self._q.get()
            if evt is None:
                return
            body = json.dumps(evt).encode()
            req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=self.timeout).close()
            except (urllib.error.URLError, OSError, TimeoutError):
                pass  # the dashboard is optional; the swarm doesn't care if it's down

    def stop(self) -> None:
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
