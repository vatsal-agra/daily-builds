"""A Node ties everything together: a TCP listen socket for inbound peer
connections, outbound connections to peers learned from the tracker, the
piece manager, and a pluggable choking policy applied on a timer. This is
the thing you actually run as `swarm seed` / `swarm leech` -- one per OS
process, exactly like a real BitTorrent client.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from . import protocol, tracker
from .choking import TitForTatChokePolicy
from .peer import PeerConnection
from .piecemanager import PieceManager
from .torrentfile import TorrentInfo

log = logging.getLogger("swarm.node")

ChokePolicy = Callable[[Dict[bytes, PeerConnection], PieceManager], Set[bytes]]


def default_choke_policy(connections: Dict[bytes, PeerConnection], piece_manager: PieceManager) -> Set[bytes]:
    """Unchoke every peer that wants something from us: no reciprocity, no
    scarcity handling. This was Phase 2's core-build policy, kept around as
    a simple baseline (and for choking.py's own tests to compare tit-for-tat
    against) -- Node's real default is now TitForTatChokePolicy, below."""
    return {pid for pid, conn in connections.items() if conn.peer_interested}


def generate_peer_id() -> bytes:
    return b"-SW0001-" + os.urandom(12)


class Node:
    def __init__(
        self,
        torrent: TorrentInfo,
        file_path: str,
        tracker_url: str,
        host: str = "127.0.0.1",
        port: int = 0,
        seed: bool = False,
        peer_id: Optional[bytes] = None,
        choke_policy: Optional[ChokePolicy] = None,
        choke_interval: float = 1.0,
        announce_interval: Optional[float] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        preseed_source: Optional[str] = None,
        preseed_pieces: Optional[Set[int]] = None,
        dashboard_url: Optional[str] = None,
    ):
        self.torrent = torrent
        self.info_hash = torrent.info_hash()
        self.tracker_url = tracker_url
        self.peer_id = peer_id or generate_peer_id()
        self.piece_manager = PieceManager(
            torrent, file_path, seed=seed, preseed_source=preseed_source, preseed_pieces=preseed_pieces
        )
        self.choke_policy = choke_policy if choke_policy is not None else TitForTatChokePolicy()
        self.choke_interval = choke_interval
        self.announce_interval = announce_interval
        self._on_event = on_event or (lambda evt: None)
        self._reporter = None
        if dashboard_url:
            from .dashboard import EventReporter

            self._reporter = EventReporter(dashboard_url)

        self.connections: Dict[bytes, PeerConnection] = {}
        self._conn_lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._sent_completed_event = seed  # a seeder never needs to announce "completed"

        self.listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_sock.bind((host, port))
        self.listen_sock.listen(16)
        self.host = host
        self.port = self.listen_sock.getsockname()[1]

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        self.emit(
            {
                "type": "hello",
                "port": self.port,
                "info_hash": self.info_hash.hex(),
                "torrent_name": self.torrent.name,
                "num_pieces": self.piece_manager.num_pieces,
                "have_bitfield": self.piece_manager.have_bitfield_bytes().hex(),
            }
        )
        self._spawn(self._accept_loop, "accept")
        self._spawn(self._choke_loop, "choke")
        self._spawn(self._tracker_loop, "tracker")

    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, daemon=True, name=f"node-{name}-{self.port}")
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        try:
            tracker.announce(self.tracker_url, self.info_hash, self.peer_id, self.port, left=self._bytes_left(), event="stopped")
        except Exception:
            pass
        try:
            self.listen_sock.close()
        except OSError:
            pass
        with self._conn_lock:
            conns = list(self.connections.values())
        for conn in conns:
            conn.close()
        for t in self._threads:
            t.join(timeout=2)
        if self._reporter is not None:
            self._reporter.stop()

    def wait_until_complete(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.piece_manager.is_complete():
            if self._stop.is_set():
                return False
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.05)
        return True

    # -- accepting / connecting --------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                sock, addr = self.listen_sock.accept()
            except OSError:
                return  # listen socket closed -> stop() was called
            threading.Thread(target=self._handle_incoming, args=(sock, addr), daemon=True).start()

    def _handle_incoming(self, sock: socket.socket, addr: Tuple[str, int]) -> None:
        try:
            hs = protocol.read_handshake(sock)
            if hs.info_hash != self.info_hash:
                log.info("rejecting %s: wrong info_hash", addr)
                sock.close()
                return
            protocol.send_handshake(sock, self.info_hash, self.peer_id)
        except (ConnectionError, OSError, protocol.ProtocolError) as exc:
            log.info("handshake with %s failed: %s", addr, exc)
            try:
                sock.close()
            except OSError:
                pass
            return
        self._register_connection(sock, hs.peer_id, addr, outbound=False)

    def connect_to_peer(self, ip: str, port: int) -> bool:
        if (ip, port) == (self.host, self.port):
            return False
        try:
            sock = socket.create_connection((ip, port), timeout=5)
            protocol.send_handshake(sock, self.info_hash, self.peer_id)
            hs = protocol.read_handshake(sock)
        except (ConnectionError, OSError, protocol.ProtocolError) as exc:
            log.info("connect to %s:%s failed: %s", ip, port, exc)
            return False
        if hs.info_hash != self.info_hash:
            sock.close()
            return False
        if hs.peer_id == self.peer_id:
            sock.close()  # connected to ourselves, e.g. via a stale tracker entry
            return False
        self._register_connection(sock, hs.peer_id, (ip, port), outbound=True)
        return True

    def _register_connection(self, sock: socket.socket, remote_peer_id: bytes, addr: Tuple[str, int], outbound: bool) -> None:
        with self._conn_lock:
            if remote_peer_id in self.connections:
                log.debug("dedup: closing duplicate %s connection to %s (%s)", "outbound" if outbound else "inbound", remote_peer_id.hex()[:8], addr)
                sock.close()  # already connected to this peer; one edge per peer pair
                return
            conn = PeerConnection(sock, remote_peer_id, addr, self, outbound)
            self.connections[remote_peer_id] = conn
        log.debug("registered %s connection to %s (%s)", "outbound" if outbound else "inbound", remote_peer_id.hex()[:8], addr)
        conn.start()
        self.emit({"type": "peer_connected", "peer": remote_peer_id.hex(), "addr": list(addr), "outbound": outbound})

    def on_peer_disconnected(self, peer_id: bytes) -> None:
        with self._conn_lock:
            self.connections.pop(peer_id, None)
        self.piece_manager.remove_peer(peer_id)
        self.emit({"type": "peer_disconnected", "peer": peer_id.hex()})

    def on_peer_interest_changed(self, conn: PeerConnection) -> None:
        # The choke loop re-evaluates on its own timer; nothing to do
        # immediately except let dashboards know state changed.
        self.emit({"type": "interest", "peer": conn.remote_peer_id.hex(), "interested": conn.peer_interested})

    def broadcast_have(self, piece_index: int) -> None:
        with self._conn_lock:
            conns = list(self.connections.values())
        for conn in conns:
            conn.send_have(piece_index)

    # -- choking -----------------------------------------------------------------

    def _choke_loop(self) -> None:
        while not self._stop.wait(self.choke_interval):
            with self._conn_lock:
                snapshot = dict(self.connections)
            if not snapshot:
                continue
            unchoke_set = self.choke_policy(snapshot, self.piece_manager)
            log.debug(
                "choke tick: %s",
                {pid.hex()[:8]: {"peer_interested": c.peer_interested, "unchoke": pid in unchoke_set} for pid, c in snapshot.items()},
            )
            for peer_id, conn in snapshot.items():
                if peer_id in unchoke_set:
                    conn.send_unchoke()
                else:
                    conn.send_choke()
            self.emit({"type": "choke_update", "unchoked": [p.hex() for p in unchoke_set]})

    # -- tracker -------------------------------------------------------------------

    def _bytes_left(self) -> int:
        have_bytes = sum(
            self.torrent.piece_size(i) for i, s in enumerate(self.piece_manager.state_snapshot()) if s == 2
        )
        return self.torrent.length - have_bytes

    def _tracker_loop(self) -> None:
        first = True
        while not self._stop.is_set():
            try:
                event = "started" if first else None
                if not self._sent_completed_event and self.piece_manager.is_complete():
                    event = "completed"
                interval, peers = tracker.announce(
                    self.tracker_url, self.info_hash, self.peer_id, self.port, left=self._bytes_left(), event=event
                )
                if event == "completed":
                    self._sent_completed_event = True
                self.emit({"type": "tracker_announce", "peers": len(peers)})
                for ip, port in peers:
                    with self._conn_lock:
                        already = any(c.remote_addr == (ip, port) for c in self.connections.values())
                    if not already:
                        threading.Thread(target=self.connect_to_peer, args=(ip, port), daemon=True).start()
            except Exception as exc:  # pragma: no cover - defensive: tracker hiccups must not kill the node
                log.warning("tracker announce failed: %s", exc)
                interval = self.announce_interval or tracker.DEFAULT_INTERVAL
            first = False
            wait_for = self.announce_interval or interval
            if self._stop.wait(wait_for):
                return

    # -- misc -------------------------------------------------------------------------

    def emit(self, evt: dict) -> None:
        evt.setdefault("node", self.peer_id.hex())
        evt.setdefault("ts", time.time())
        try:
            self._on_event(evt)
        except Exception:  # pragma: no cover - a dashboard bug must never break transfers
            log.exception("on_event callback raised")
        if self._reporter is not None:
            self._reporter.report(evt)

    def status(self) -> dict:
        with self._conn_lock:
            n_conn = len(self.connections)
        return {
            "peer_id": self.peer_id.hex(),
            "port": self.port,
            "have": self.piece_manager.have_count(),
            "total": self.piece_manager.num_pieces,
            "complete": self.piece_manager.is_complete(),
            "connections": n_conn,
        }
