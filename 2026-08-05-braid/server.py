#!/usr/bin/env python3
"""
server.py — the live collaboration relay for the Braid web editor.

This server is deliberately "dumb": it never touches CRDT logic, never
computes a document string, and never resolves a conflict. It does exactly
two things:

  1. Keeps an append-only, in-memory log of every op it has ever relayed,
     so a browser tab that connects late (or refreshes) can replay history
     and catch up to the current document — the same idea as a message
     broker's log, not a database.
  2. Broadcasts every op it receives from one client to every other
     connected client, live, over Server-Sent Events (SSE).

Every browser tab runs its own full CRDT replica (static/rga.js) and
merges ops itself. If this server crashed and only relayed events at
random, in duplicate, out of order — the browsers would *still* converge,
because that's what a CRDT guarantees. (The chaos/latency simulation in
crdt/network.py exercises exactly that claim, headlessly, in
tests/test_network_convergence.py — this server doesn't need to reprove
it, it just needs to not get in the way.)

stdlib only: http.server + threading, no Flask/FastAPI/websockets.
"""

import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def _is_valid_op_id(x):
    return (isinstance(x, list) and len(x) == 2
            and isinstance(x[0], int) and not isinstance(x[0], bool)
            and isinstance(x[1], str) and x[1] != "")


def _validate_op(op):
    """The server is a dumb relay (see module docstring) — it never
    interprets an op's CRDT meaning — but a malformed op would still get
    broadcast to every connected browser, whose CRDT engine trusts op
    shape without re-validating it (see rga.js). So the one place op
    shape *does* get checked is here, at the door, not deep inside
    someone else's merge logic."""
    if not isinstance(op, dict):
        raise ValueError("op must be an object")
    if op.get("type") not in ("insert", "delete", "restore"):
        raise ValueError(f"op.type must be insert/delete/restore, got {op.get('type')!r}")
    if not _is_valid_op_id(op.get("id")):
        raise ValueError("op.id must be a [counter:int, site:str] pair")
    if op["type"] == "insert":
        origin = op.get("origin")
        if origin is not None and not _is_valid_op_id(origin):
            raise ValueError("op.origin must be null or a [counter:int, site:str] pair")
        value = op.get("value")
        if not isinstance(value, str) or len(value) == 0:
            raise ValueError("op.value must be a non-empty string")
        if len(list(value)) != 1:
            raise ValueError("op.value must be exactly one character")
    else:  # delete / restore
        if not _is_valid_op_id(op.get("target")):
            raise ValueError("op.target must be a [counter:int, site:str] pair")


class Hub:
    """All the mutable shared state for one document, guarded by one lock.
    A real multi-document deployment would key this by document id; this
    build keeps one shared document per server process, which is enough
    to demonstrate several peers editing the same document live."""

    def __init__(self):
        self.lock = threading.Lock()
        self.op_log = []          # every op ever relayed, in relay order
        self.subscribers = {}     # site_id -> queue.Queue of SSE-ready dict events
        self.presence = {}        # site_id -> {"name":..., "cursor":..., "color":..., "last_seen":...}

    def subscribe(self, site_id):
        q = queue.Queue()
        with self.lock:
            self.subscribers[site_id] = q
        return q

    def unsubscribe(self, site_id):
        with self.lock:
            self.subscribers.pop(site_id, None)
            self.presence.pop(site_id, None)
        self._broadcast({"kind": "presence_leave", "site": site_id})

    def snapshot_ops(self):
        with self.lock:
            return list(self.op_log)

    def snapshot_presence(self):
        with self.lock:
            return dict(self.presence)

    def relay_op(self, from_site, op):
        with self.lock:
            self.op_log.append(op)
        self._broadcast({"kind": "op", "from": from_site, "op": op})

    def update_presence(self, site_id, name, cursor, color):
        with self.lock:
            self.presence[site_id] = {
                "name": name, "cursor": cursor, "color": color, "last_seen": time.time(),
            }
        self._broadcast({"kind": "presence", "site": site_id, "name": name,
                          "cursor": cursor, "color": color})

    def _broadcast(self, event):
        with self.lock:
            targets = list(self.subscribers.items())
        for site_id, q in targets:
            q.put(event)


HUB = Hub()


class Handler(BaseHTTPRequestHandler):
    server_version = "Braid/1.0"
    # BaseHTTPRequestHandler defaults to HTTP/1.0, which closes the TCP
    # connection after every single response — brutal when a fast typist
    # fires a POST /op per keystroke, since each one pays a fresh TCP
    # handshake. HTTP/1.1 + the Content-Length we already send on every
    # response lets the browser keep-alive and reuse one connection.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep the demo output quiet; errors still raise/print via BaseHTTPRequestHandler

    # ---- routing -----------------------------------------------------------

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self._serve_file("index.html")
        elif self.path.startswith("/static/"):
            self._serve_file(self.path[len("/static/"):])
        elif self.path.startswith("/events"):
            self._handle_sse()
        else:
            self.send_error(404, "not found")

    def do_POST(self):
        if self.path == "/op":
            self._handle_post_op()
        elif self.path == "/presence":
            self._handle_post_presence()
        else:
            self.send_error(404, "not found")

    # ---- static files -----------------------------------------------------

    def _serve_file(self, rel_path):
        rel_path = rel_path.split("?", 1)[0]
        safe_path = os.path.normpath(os.path.join(STATIC_DIR, rel_path))
        # `safe_path.startswith(STATIC_DIR)` alone is a classic trap: a
        # sibling directory named e.g. "static-evil" also starts with the
        # string "static", so a bare prefix check can be walked right past
        # the intended root. Require an exact match or a path *under* it
        # (STATIC_DIR + separator), not just a string that happens to
        # start with the same characters.
        if safe_path != STATIC_DIR and not safe_path.startswith(STATIC_DIR + os.sep):
            self.send_error(403, "forbidden")
            return
        if not os.path.isfile(safe_path):
            self.send_error(404, "not found")
            return
        ext = os.path.splitext(safe_path)[1]
        content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(safe_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---- SSE stream ---------------------------------------------------------

    def _handle_sse(self):
        query = self._query_params()
        site_id = query.get("site", [None])[0]
        if not site_id:
            self.send_error(400, "missing ?site=")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # bootstrap: replay full history + current presence before going live,
        # so a late-joining (or refreshed) tab catches up deterministically
        try:
            self._write_event({"kind": "bootstrap", "ops": HUB.snapshot_ops(),
                                "presence": HUB.snapshot_presence()})
        except (BrokenPipeError, ConnectionResetError):
            return

        q = HUB.subscribe(site_id)
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                    self._write_event(event)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # SSE comment, prevents idle timeouts
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            HUB.unsubscribe(site_id)

    def _write_event(self, event):
        data = json.dumps(event)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    # ---- POST endpoints -----------------------------------------------------

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def _handle_post_op(self):
        try:
            body = self._read_json_body()
            from_site = body["from"]
            op = body["op"]
            _validate_op(op)
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
            self.send_error(400, f"bad request: {e}")
            return
        HUB.relay_op(from_site, op)
        self._send_json(200, {"ok": True})

    def _handle_post_presence(self):
        try:
            body = self._read_json_body()
            site_id = body["site"]
        except (KeyError, json.JSONDecodeError) as e:
            self.send_error(400, f"bad request: {e}")
            return
        HUB.update_presence(site_id, body.get("name", site_id), body.get("cursor"), body.get("color", "#888"))
        self._send_json(200, {"ok": True})

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query_params(self):
        from urllib.parse import urlparse, parse_qs
        return parse_qs(urlparse(self.path).query)


def run_server(port=8420):
    addr = ("0.0.0.0", port)
    try:
        httpd = ThreadingHTTPServer(addr, Handler)
    except OSError as e:
        if e.errno == 98:  # EADDRINUSE
            print(f"error: port {port} is already in use — is Braid (or something else) "
                  f"already running there?")
            print(f"try: braid serve --port {port + 1}")
        else:
            print(f"error: couldn't start the server on port {port}: {e}")
        raise SystemExit(1)
    print(f"Braid collaborative editor running at http://localhost:{port}/")
    print("Open it in two or more browser tabs to see live CRDT sync.")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
        httpd.shutdown()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8420)
    args = p.parse_args()
    run_server(port=args.port)
