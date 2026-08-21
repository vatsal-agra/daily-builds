"""The real-time multiplayer document server.

Architecture, per room:

- A `mirror` RGA (the room's canonical, always-immediately-updated copy)
  applies every op the instant a client sends it, through a causal
  buffer — this is what bootstraps late joiners with the full document.
- A `SimNetwork` — the *exact same class* `verify/convergence.py` proves
  SEC against offline — handles the *fan-out* to every other connected
  client. A client's own edits appear instantly for them (optimistic
  local apply happens in the browser); everyone else gets it after
  whatever latency/loss/duplication/partition the live chaos-control
  panel currently has dialed in. This is not a simulated demo bolted on
  top of a "real" server — it IS the real transport for every op that
  isn't your own.
- One background thread ticks the network for all rooms and pushes
  whatever comes due out over each room's real WebSocket connections.

Cursor presence pings ride the same chaos-affected channel (so heavy
latency/partition visibly stalls peer cursors too), anchored to a node
id rather than a raw offset so a stale cursor still lands on the right
character after concurrent edits shift everyone else's indices.
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crdt.clock import CausalDeliveryBuffer
from crdt.rga import RGA
from network.sim_network import SimNetwork
from server import ws

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TICK_SECONDS = 0.04


class Room:
    def __init__(self, name: str, seed: int = 1):
        self.name = name
        self.lock = threading.RLock()
        self.mirror = RGA("__mirror__")
        self.mirror_buffer = CausalDeliveryBuffer(self.mirror.has_id)
        self.net = SimNetwork([], seed=seed, latency_range=(1, 4), loss_p=0.0, dup_p=0.0)
        self.clients: dict[str, "ClientConn"] = {}
        self.cursors: dict[str, dict] = {}  # peer_id -> {"after": node_id or None}

    def set_chaos(self, latency_range=None, loss_p=None, dup_p=None):
        with self.lock:
            if latency_range is not None:
                self.net.latency_range = tuple(latency_range)
            if loss_p is not None:
                self.net.loss_p = loss_p
            if dup_p is not None:
                self.net.dup_p = dup_p

    def add_client(self, peer_id: str, conn: "ClientConn"):
        with self.lock:
            self.clients[peer_id] = conn
            if peer_id not in self.net.peer_ids:
                self.net.peer_ids.append(peer_id)
            snapshot = list(self.mirror.op_log)
            cursors_snapshot = dict(self.cursors)
        conn.send_json({"type": "bootstrap", "ops": [_op_to_wire(o) for o in snapshot],
                         "cursors": cursors_snapshot, "peers": list(self.clients.keys())})
        self._broadcast_presence()

    def remove_client(self, peer_id: str):
        with self.lock:
            self.clients.pop(peer_id, None)
            self.cursors.pop(peer_id, None)
        self._broadcast_presence()

    def _broadcast_presence(self):
        with self.lock:
            peers = list(self.clients.keys())
            targets = list(self.clients.values())
        msg = json.dumps({"type": "presence", "peers": peers})
        for c in targets:
            c.send_raw(msg)

    def handle_op(self, src_peer: str, op: dict):
        with self.lock:
            self.mirror_buffer.submit(op, self.mirror.apply_remote)
            others = [p for p in self.clients if p != src_peer]
            self.net.broadcast(src_peer, op, dsts=others)

    def handle_cursor(self, src_peer: str, after):
        with self.lock:
            self.cursors[src_peer] = {"after": after}
            others = [p for p in self.clients if p != src_peer]
            self.net.broadcast(src_peer, {"type": "cursor", "peer": src_peer, "after": after,
                                           "deps": () if after is None else (tuple(after),)},
                                dsts=others)

    def tick(self):
        with self.lock:
            def deliver(dst_peer, wire_op):
                client = self.clients.get(dst_peer)
                if client is not None:
                    client.send_json(wire_op)

            self.net.step(deliver)


def _op_to_wire(op: dict) -> dict:
    """Op ids/parents are Python tuples internally; JSON only has lists,
    so this is a pure representation change (round-tripped back to tuples
    on receipt) — not a protocol/semantic difference."""
    return op


def _wire_to_op(msg: dict) -> dict:
    out = dict(msg)
    if "id" in out and out["id"] is not None:
        out["id"] = tuple(out["id"])
    if "parent" in out and out["parent"] is not None:
        out["parent"] = tuple(out["parent"])
    if "deps" in out:
        out["deps"] = tuple(tuple(d) if d is not None else None for d in out["deps"])
    return out


class ClientConn:
    def __init__(self, conn, peer_id, room):
        self.conn = conn
        self.peer_id = peer_id
        self.room = room
        self._send_lock = threading.Lock()

    def send_json(self, obj):
        self.send_raw(json.dumps(obj))

    def send_raw(self, text):
        with self._send_lock:
            try:
                ws.send_text(self.conn, text)
            except OSError:
                pass


class BraidServer:
    def __init__(self, host="127.0.0.1", port=8765, seed=1):
        self.host = host
        self.port = port
        self.seed = seed
        self.rooms: dict[str, Room] = {}
        self.rooms_lock = threading.Lock()
        self._sock = None
        self._running = False

    def get_room(self, name: str) -> Room:
        with self.rooms_lock:
            if name not in self.rooms:
                self.rooms[name] = Room(name, seed=self.seed)
            return self.rooms[name]

    def _ticker_loop(self):
        while self._running:
            with self.rooms_lock:
                rooms = list(self.rooms.values())
            for room in rooms:
                room.tick()
            time.sleep(TICK_SECONDS)

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(64)
        self._running = True
        threading.Thread(target=self._ticker_loop, daemon=True).start()
        print(f"Braid server listening on http://{self.host}:{self.port}")
        try:
            while self._running:
                conn, addr = self._sock.accept()
                threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------------

    def _handle_connection(self, conn):
        try:
            method, path, headers = ws.parse_http_request(conn)
        except (OSError, ValueError):
            conn.close()
            return
        if method is None:
            conn.close()
            return
        if ws.is_websocket_upgrade(headers) and path.startswith("/ws"):
            self._handle_ws(conn, path, headers)
        else:
            self._handle_http(conn, path)

    def _handle_http(self, conn, path):
        route = path.split("?", 1)[0]
        if route == "/":
            route = "/index.html"
        if route.startswith("/api/chaos"):
            self._handle_chaos_api(conn, path)
            return
        safe = os.path.normpath(route).lstrip(os.sep)
        file_path = os.path.join(STATIC_DIR, safe)
        if not file_path.startswith(STATIC_DIR) or not os.path.isfile(file_path):
            self._send_http(conn, 404, "text/plain", b"not found")
            return
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            body = f.read()
        self._send_http(conn, 200, content_type, body)

    def _handle_chaos_api(self, conn, path):
        from urllib.parse import urlparse, parse_qs

        qs = parse_qs(urlparse(path).query)
        room_name = qs.get("room", ["default"])[0]
        room = self.get_room(room_name)
        kwargs = {}
        if "loss" in qs:
            kwargs["loss_p"] = float(qs["loss"][0])
        if "dup" in qs:
            kwargs["dup_p"] = float(qs["dup"][0])
        if "lat_min" in qs and "lat_max" in qs:
            kwargs["latency_range"] = (int(qs["lat_min"][0]), int(qs["lat_max"][0]))
        room.set_chaos(**kwargs)
        if "partition" in qs:
            groups = qs["partition"][0].split("|")
            if len(groups) == 2:
                a = [p for p in groups[0].split(",") if p]
                if groups[1] == "__others__":
                    with room.lock:
                        b = [p for p in room.clients if p not in a]
                else:
                    b = [p for p in groups[1].split(",") if p]
                ticks = int(qs.get("ticks", [50])[0])
                if a and b:
                    room.net.partition(a, b, ticks)
        if "heal" in qs:
            room.net.heal_all()
        body = json.dumps({
            "loss_p": room.net.loss_p, "dup_p": room.net.dup_p,
            "latency_range": list(room.net.latency_range),
            "peers": list(room.clients.keys()),
        }).encode()
        self._send_http(conn, 200, "application/json", body)

    def _send_http(self, conn, status, content_type, body: bytes):
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found"}.get(status, "OK")
        headers = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        try:
            conn.sendall(headers + body)
        finally:
            conn.close()

    def _handle_ws(self, conn, path, headers):
        from urllib.parse import urlparse, parse_qs

        qs = parse_qs(urlparse(path).query)
        room_name = qs.get("room", ["default"])[0]
        peer_id = qs.get("peer", [None])[0] or f"anon-{id(conn)}"
        room = self.get_room(room_name)
        ws.do_handshake(conn, headers)
        client = ClientConn(conn, peer_id, room)
        room.add_client(peer_id, client)
        try:
            while True:
                text = ws.recv_text(conn)
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") in ("insert", "delete"):
                    room.handle_op(peer_id, _wire_to_op(msg))
                elif msg.get("type") == "cursor":
                    after = msg.get("after")
                    room.handle_cursor(peer_id, tuple(after) if after is not None else None)
        except ws.WebSocketClosed:
            pass
        except OSError:
            pass
        finally:
            room.remove_client(peer_id)
            try:
                conn.close()
            except OSError:
                pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Braid collaborative-editing server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    BraidServer(args.host, args.port, seed=args.seed).start()


if __name__ == "__main__":
    main()
