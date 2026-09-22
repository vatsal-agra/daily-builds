"""A real HTTP BitTorrent tracker (BEP-3's `/announce`) plus `/scrape`.

Peers don't find each other by magic: a tracker is a plain, dumb, stateless-
between-requests rendezvous point. It never sees file content and doesn't
participate in transfers; it only remembers, per swarm (`info_hash`), which
peers announced recently and hands each requester everyone *else's*
address. Every response is real bencode, and the compact peer format is the
real 6-bytes-per-peer (4 IPv4 + 2 port big-endian) wire format BitTorrent
clients actually exchange -- decodable by anything that speaks the spec,
not just this codebase.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

from . import bencode

DEFAULT_INTERVAL = 5  # seconds; short on purpose so the demo converges fast
PEER_EXPIRY_MULTIPLIER = 3  # a peer not re-announcing within interval*this is dropped


@dataclass
class PeerRecord:
    ip: str
    port: int
    left: int
    last_seen: float = field(default_factory=time.time)


class SwarmTable:
    """info_hash -> peer_id -> PeerRecord, with time-based expiry."""

    def __init__(self, interval: int = DEFAULT_INTERVAL):
        self.interval = interval
        self._lock = threading.Lock()
        self._swarms: Dict[bytes, Dict[bytes, PeerRecord]] = {}

    def announce(self, info_hash: bytes, peer_id: bytes, ip: str, port: int, left: int, event: Optional[str]) -> List[Tuple[bytes, str, int]]:
        with self._lock:
            swarm = self._swarms.setdefault(info_hash, {})
            self._expire_locked(swarm)
            if event == "stopped":
                swarm.pop(peer_id, None)
            else:
                swarm[peer_id] = PeerRecord(ip=ip, port=port, left=left)
            return [(pid, rec.ip, rec.port) for pid, rec in swarm.items() if pid != peer_id]

    def _expire_locked(self, swarm: Dict[bytes, PeerRecord]) -> None:
        cutoff = time.time() - self.interval * PEER_EXPIRY_MULTIPLIER
        stale = [pid for pid, rec in swarm.items() if rec.last_seen < cutoff]
        for pid in stale:
            del swarm[pid]

    def scrape(self, info_hash: bytes) -> Tuple[int, int]:
        """Returns (complete, incomplete) counts for a swarm."""
        with self._lock:
            swarm = self._swarms.get(info_hash, {})
            self._expire_locked(swarm)
            complete = sum(1 for rec in swarm.values() if rec.left == 0)
            incomplete = len(swarm) - complete
            return complete, incomplete


def _pack_compact_peers(peers: List[Tuple[bytes, str, int]]) -> bytes:
    out = bytearray()
    for _pid, ip, port in peers:
        out += socket.inet_aton(ip)
        out += struct.pack(">H", port)
    return bytes(out)


class _TrackerHandler(BaseHTTPRequestHandler):
    server: "TrackerServer"

    def log_message(self, fmt, *args):  # noqa: A003 - silence stdlib default logging
        pass

    def _send_bencoded(self, obj, status: int = 200) -> None:
        body = bencode.encode(obj)
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib method name
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/announce":
            self._handle_announce(parsed.query)
        elif parsed.path == "/scrape":
            self._handle_scrape(parsed.query)
        else:
            self._send_bencoded({b"failure reason": b"unknown endpoint"}, status=404)

    def _parse_raw_query(self, query: str) -> Dict[str, bytes]:
        """Percent-decode each value to raw bytes ourselves: info_hash and
        peer_id are arbitrary 20-byte binary strings, not text, and stdlib
        parse_qs's str-based decoding would mangle bytes that aren't valid
        UTF-8 (any peer_id/info_hash byte >= 0x80, which is common)."""
        params: Dict[str, bytes] = {}
        for part in query.split("&"):
            if not part or "=" not in part:
                continue
            key, _, value = part.partition("=")
            params[key] = urllib.parse.unquote_to_bytes(value)
        return params

    def _handle_announce(self, query: str) -> None:
        params = self._parse_raw_query(query)
        try:
            info_hash = params["info_hash"]
            peer_id = params["peer_id"]
            port = int(params["port"].decode("ascii"))
            left = int(params.get("left", b"0").decode("ascii"))
            event = params.get("event", b"").decode("ascii") or None
            compact = params.get("compact", b"0").decode("ascii") == "1"
        except (KeyError, ValueError) as exc:
            self._send_bencoded({b"failure reason": f"malformed announce: {exc}".encode()}, status=400)
            return
        if len(info_hash) != 20 or len(peer_id) != 20:
            self._send_bencoded({b"failure reason": b"info_hash/peer_id must be 20 bytes"}, status=400)
            return
        if not (0 < port <= 65535):
            # A bad/hostile port here would otherwise surface much later as
            # an unhandled struct.error inside _pack_compact_peers when some
            # *other* peer's announce tries to pack this one into a
            # response -- reject it at the source instead.
            self._send_bencoded({b"failure reason": b"port must be in 1..65535"}, status=400)
            return
        if left < 0:
            self._send_bencoded({b"failure reason": b"left must be >= 0"}, status=400)
            return

        client_ip = self.client_address[0]
        peers = self.server.swarm_table.announce(info_hash, peer_id, client_ip, port, left, event)

        response: Dict[bytes, object] = {b"interval": self.server.swarm_table.interval}
        if compact:
            response[b"peers"] = _pack_compact_peers(peers)
        else:
            response[b"peers"] = [
                {b"peer id": pid, b"ip": ip.encode(), b"port": p} for pid, ip, p in peers
            ]
        self._send_bencoded(response)

    def _handle_scrape(self, query: str) -> None:
        params = self._parse_raw_query(query)
        info_hash = params.get("info_hash")
        if info_hash is None or len(info_hash) != 20:
            self._send_bencoded({b"failure reason": b"scrape requires a 20-byte info_hash"}, status=400)
            return
        complete, incomplete = self.server.swarm_table.scrape(info_hash)
        self._send_bencoded({b"files": {info_hash: {b"complete": complete, b"incomplete": incomplete, b"downloaded": complete}}})


class TrackerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, interval: int = DEFAULT_INTERVAL):
        super().__init__((host, port), _TrackerHandler)
        self.swarm_table = SwarmTable(interval=interval)


def run_tracker(host: str = "127.0.0.1", port: int = 6969, interval: int = DEFAULT_INTERVAL) -> TrackerServer:
    """Start a tracker HTTP server on a background thread and return it
    (call .shutdown() + .server_close() to stop it)."""
    server = TrackerServer(host, port, interval=interval)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._thread = thread  # type: ignore[attr-defined]
    return server


# -- client-side announce helper, used by node.py and by anyone speaking
#    to a real tracker without pulling in the rest of swarm's networking --

def announce(
    tracker_url: str,
    info_hash: bytes,
    peer_id: bytes,
    port: int,
    left: int,
    event: Optional[str] = None,
    compact: bool = True,
    timeout: float = 5.0,
) -> Tuple[int, List[Tuple[str, int]]]:
    query = {
        "info_hash": info_hash,
        "peer_id": peer_id,
        "port": str(port),
        "left": str(left),
        "compact": "1" if compact else "0",
    }
    if event:
        query["event"] = event
    encoded = "&".join(
        f"{k}={urllib.parse.quote_from_bytes(v) if isinstance(v, (bytes, bytearray)) else urllib.parse.quote(v)}"
        for k, v in query.items()
    )
    url = f"{tracker_url}?{encoded}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        body = resp.read()
    data = bencode.decode(body)
    if b"failure reason" in data:
        raise RuntimeError(f"tracker announce failed: {data[b'failure reason'].decode(errors='replace')}")
    interval = data[b"interval"]
    raw_peers = data[b"peers"]
    peers: List[Tuple[str, int]] = []
    if isinstance(raw_peers, bytes):
        for i in range(0, len(raw_peers), 6):
            chunk = raw_peers[i : i + 6]
            ip = socket.inet_ntoa(chunk[:4])
            (p,) = struct.unpack(">H", chunk[4:6])
            peers.append((ip, p))
    else:
        for entry in raw_peers:
            peers.append((entry[b"ip"].decode(), entry[b"port"]))
    return interval, peers
