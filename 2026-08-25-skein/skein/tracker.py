"""A real BitTorrent-style HTTP tracker.

The tracker never sees or forwards file bytes — it only helps peers
find each other. Peers periodically GET /announce with their info_hash,
peer_id, listening port, and transfer stats; the tracker replies with a
*compact* peer list (the real BEP 23 format: each peer packed into 6
raw bytes — 4-byte IPv4 + 2-byte big-endian port — instead of a bencoded
list of dicts) for that swarm, and forgets peers that stop announcing
(so a crashed peer doesn't linger in a swarm forever).
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote_to_bytes

from . import bencode

PEER_TIMEOUT = 90.0  # seconds without a re-announce before a peer is dropped
DEFAULT_INTERVAL = 30  # seconds we ask peers to wait between announces


class PeerRecord:
    __slots__ = ("peer_id", "ip", "port", "uploaded", "downloaded", "left", "last_seen")

    def __init__(self, peer_id, ip, port):
        self.peer_id = peer_id
        self.ip = ip
        self.port = port
        self.uploaded = 0
        self.downloaded = 0
        self.left = 0
        self.last_seen = time.time()


def _parse_query_raw(query: str) -> dict:
    """Parse a query string into {key: raw_bytes}, percent-decoding each
    value to raw bytes rather than a str — info_hash/peer_id are 20
    arbitrary bytes, not valid UTF-8 in general, so urllib.parse.parse_qs
    (which decodes to str) would corrupt them.
    """
    out = {}
    if not query:
        return out
    for pair in query.split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        out[unquote_to_bytes(k).decode("ascii")] = unquote_to_bytes(v)
    return out


def pack_compact_peers(records) -> bytes:
    out = bytearray()
    for r in records:
        out += socket.inet_aton(r.ip) + struct.pack(">H", r.port)
    return bytes(out)


class Swarm:
    def __init__(self):
        self.peers: dict[bytes, PeerRecord] = {}
        self._lock = threading.RLock()

    def announce(self, info_hash, peer_id, ip, port, uploaded, downloaded, left, event):
        with self._lock:
            if event == "stopped":
                self.peers.pop(peer_id, None)
                return
            rec = self.peers.get(peer_id)
            if rec is None:
                rec = PeerRecord(peer_id, ip, port)
                self.peers[peer_id] = rec
            rec.ip, rec.port = ip, port
            rec.uploaded, rec.downloaded, rec.left = uploaded, downloaded, left
            rec.last_seen = time.time()

    def sweep_expired(self):
        now = time.time()
        with self._lock:
            dead = [pid for pid, r in self.peers.items() if now - r.last_seen > PEER_TIMEOUT]
            for pid in dead:
                del self.peers[pid]

    def snapshot(self, exclude_peer_id=None):
        with self._lock:
            return [r for pid, r in self.peers.items() if pid != exclude_peer_id]

    def counts(self):
        with self._lock:
            complete = sum(1 for r in self.peers.values() if r.left == 0)
            incomplete = len(self.peers) - complete
            return complete, incomplete


class TrackerState:
    def __init__(self):
        self._swarms: dict[bytes, Swarm] = {}
        self._lock = threading.RLock()

    def swarm_for(self, info_hash: bytes) -> Swarm:
        with self._lock:
            s = self._swarms.get(info_hash)
            if s is None:
                s = Swarm()
                self._swarms[info_hash] = s
            return s

    def all_info_hashes(self):
        with self._lock:
            return list(self._swarms.keys())


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep test/demo output quiet; real errors still raise

    def _send_bencoded(self, obj, status=200):
        body = bencode.encode(obj)
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = urlsplit(self.path)
        state: TrackerState = self.server.tracker_state  # type: ignore[attr-defined]

        if parts.path == "/announce":
            self._handle_announce(parts.query, state)
        elif parts.path == "/scrape":
            self._handle_scrape(parts.query, state)
        else:
            self._send_bencoded({b"failure reason": b"unknown endpoint"}, status=404)

    def _handle_announce(self, query, state: TrackerState):
        params = _parse_query_raw(query)
        try:
            info_hash = params["info_hash"]
            peer_id = params["peer_id"]
            port = int(params["port"])
        except (KeyError, ValueError):
            self._send_bencoded({b"failure reason": b"missing/invalid required parameter"}, 400)
            return
        if len(info_hash) != 20 or len(peer_id) != 20:
            self._send_bencoded({b"failure reason": b"info_hash/peer_id must be 20 bytes"}, 400)
            return

        uploaded = int(params.get("uploaded", b"0") or b"0")
        downloaded = int(params.get("downloaded", b"0") or b"0")
        left = int(params.get("left", b"0") or b"0")
        event = params.get("event", b"").decode("ascii", errors="ignore")
        ip = self.client_address[0]

        swarm = state.swarm_for(info_hash)
        swarm.announce(info_hash, peer_id, ip, port, uploaded, downloaded, left, event)
        swarm.sweep_expired()

        peers = swarm.snapshot(exclude_peer_id=peer_id)
        response = {
            b"interval": DEFAULT_INTERVAL,
            b"complete": sum(1 for r in peers if r.left == 0),
            b"incomplete": sum(1 for r in peers if r.left != 0),
            b"peers": pack_compact_peers(peers),
        }
        self._send_bencoded(response)

    def _handle_scrape(self, query, state: TrackerState):
        params = _parse_query_raw(query)
        hashes = params.get("info_hash")
        targets = [hashes] if hashes else state.all_info_hashes()
        files = {}
        for ih in targets:
            swarm = state.swarm_for(ih)
            complete, incomplete = swarm.counts()
            files[ih] = {b"complete": complete, b"incomplete": incomplete, b"downloaded": complete}
        self._send_bencoded({b"files": files})


class TrackerServer:
    """A real HTTP tracker you can start/stop programmatically (for tests
    and the `skein swarm` demo) or run standalone via the CLI.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.state = TrackerState()
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.tracker_state = self.state  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)
