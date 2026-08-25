"""A Skein node: announces to a tracker, accepts and dials real TCP peer
connections, and drives piece exchange using rarest-first selection and
tit-for-tat choking.

Threading model: one background thread per peer connection (handles
that connection's handshake, message loop, and request pipelining),
plus three node-wide background threads: `_accept_loop` (listens for
inbound connections), `_announce_loop` (periodically re-announces to
the tracker and dials any newly-discovered peers), and `_choke_loop`
(periodically re-runs the tit-for-tat decision and sends choke/unchoke
messages). All shared state (the piece manager, the choke manager, the
connection table, the event log) is protected by locks so this holds
up under real concurrent access, not just in the common case.
"""

from __future__ import annotations

import os
import random
import socket
import struct
import threading
import time
import urllib.request
from urllib.parse import quote_from_bytes

from . import bencode, wire
from .choke import ChokeManager
from .piecemanager import PieceManager, PieceError, block_plan, BLOCK_SIZE

REQUEST_PIPELINE_DEPTH = 8   # outstanding block requests per peer
REQUEST_RETRY_TIMEOUT = 8.0  # seconds before an un-answered request is re-issued
SOCKET_POLL_TIMEOUT = 0.5    # recv_message timeout so loops stay responsive


def make_peer_id() -> bytes:
    # Real convention: "-<2 letter client id><4 digit version>-" then random.
    prefix = b"-SK0001-"
    return prefix + os.urandom(20 - len(prefix))


class EventLog:
    """Thread-safe append-only log of real swarm events, timestamped
    relative to node start. Consumed by the CLI's `viz` command to
    render an interactive replay of an actual run (never synthetic data).
    """

    def __init__(self):
        self._t0 = time.time()
        self._lock = threading.Lock()
        self.events: list[dict] = []

    def log(self, kind: str, **fields):
        with self._lock:
            self.events.append({"t": round(time.time() - self._t0, 4), "kind": kind, **fields})

    def snapshot(self):
        with self._lock:
            return list(self.events)


class PeerConn:
    """State for one live peer connection (either direction)."""

    def __init__(self, sock: socket.socket, peer_id: bytes, addr, outgoing: bool):
        self.sock = sock
        self.peer_id = peer_id
        self.peer_key = peer_id.hex()
        self.addr = addr
        self.outgoing = outgoing
        self.peer_has: set[int] = set()
        self.am_choking = True
        self.am_interested = False
        self.peer_choking = True
        self.peer_interested = False
        self.pending: dict[tuple, float] = {}  # (index, offset) -> request_time
        self.lock = threading.Lock()
        self.alive = True


class Node:
    def __init__(
        self,
        torrent,
        dest_path: str,
        tracker_url: str,
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
        have_all: bool = False,
        name: str = "node",
        choke_interval: float = 3.0,
        announce_interval: float = 2.0,
        resume: bool = True,
    ):
        self.torrent = torrent
        self.name = name
        self.peer_id = make_peer_id()
        self.tracker_url = tracker_url
        self.pm = PieceManager(torrent, dest_path, have_all=have_all, resume=resume)
        self.choke_mgr = ChokeManager(is_seed=have_all)
        self.events = EventLog()
        self.choke_interval = choke_interval
        self.announce_interval = announce_interval

        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind((listen_host, listen_port))
        self._listen_sock.listen(16)
        self.listen_host, self.listen_port = self._listen_sock.getsockname()

        self._conns: dict[str, PeerConn] = {}
        self._conns_lock = threading.RLock()
        self._known_addrs: set[tuple] = set()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._uploaded_total = 0
        self._downloaded_total = 0

        self.events.log("start", name=name, listen_port=self.listen_port,
                         have_all=have_all, num_pieces=torrent.num_pieces,
                         recovered_on_resume=self.pm.recovered_on_resume)

    # -- lifecycle --------------------------------------------------

    def start(self):
        self._threads.append(threading.Thread(target=self._accept_loop, daemon=True))
        self._threads.append(threading.Thread(target=self._announce_loop, daemon=True))
        self._threads.append(threading.Thread(target=self._choke_loop, daemon=True))
        for t in self._threads:
            t.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self._announce(event="stopped")
        except OSError:
            pass
        try:
            self._listen_sock.close()
        except OSError:
            pass
        with self._conns_lock:
            conns = list(self._conns.values())
        for c in conns:
            try:
                c.sock.close()
            except OSError:
                pass
        for t in self._threads:
            t.join(timeout=2)

    def wait_until_complete(self, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.pm.is_complete():
                return True
            time.sleep(0.1)
        return self.pm.is_complete()

    # -- tracker ------------------------------------------------------

    def _announce(self, event: str = ""):
        left = self.torrent.total_length - self.pm.bytes_have()
        params = {
            "info_hash": self.torrent.info_hash,
            "peer_id": self.peer_id,
            "port": str(self.listen_port).encode(),
            "uploaded": str(self._uploaded_total).encode(),
            "downloaded": str(self._downloaded_total).encode(),
            "left": str(left).encode(),
        }
        if event:
            params["event"] = event.encode()
        qs = "&".join(f"{k}={quote_from_bytes(v)}" for k, v in params.items())
        url = f"{self.tracker_url}/announce?{qs}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read()
        data = bencode.decode(body)
        if b"failure reason" in data:
            raise RuntimeError(f"tracker error: {data[b'failure reason']!r}")
        peers_raw = data.get(b"peers", b"")
        peers = []
        for i in range(0, len(peers_raw), 6):
            chunk = peers_raw[i:i + 6]
            ip = socket.inet_ntoa(chunk[:4])
            (port,) = struct.unpack(">H", chunk[4:6])
            peers.append((ip, port))
        return peers

    def _announce_loop(self):
        # Announce immediately, then periodically.
        while not self._stop.is_set():
            try:
                peers = self._announce(event="started" if not self._known_addrs else "")
                for addr in peers:
                    if addr == (self.listen_host, self.listen_port):
                        continue
                    if addr in self._known_addrs:
                        continue
                    self._known_addrs.add(addr)
                    self.events.log("discover_peer", addr=list(addr))
                    threading.Thread(target=self._dial, args=(addr,), daemon=True).start()
            except Exception as e:  # tracker hiccup shouldn't kill the node
                self.events.log("announce_error", error=str(e))
            self._stop.wait(self.announce_interval)

    # -- connection setup -----------------------------------------------

    def _accept_loop(self):
        self._listen_sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                sock, addr = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle_incoming, args=(sock, addr), daemon=True).start()

    def _handle_incoming(self, sock: socket.socket, addr):
        try:
            info_hash, peer_id = wire.recv_handshake(sock)
            if info_hash != self.torrent.info_hash:
                sock.close()
                return
            wire.send_handshake(sock, self.torrent.info_hash, self.peer_id)
        except wire.WireError:
            sock.close()
            return
        self._run_connection(sock, peer_id, addr, outgoing=False)

    def _dial(self, addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(5)
            sock.connect(addr)
            wire.send_handshake(sock, self.torrent.info_hash, self.peer_id)
            info_hash, peer_id = wire.recv_handshake(sock)
            if info_hash != self.torrent.info_hash:
                sock.close()
                return
        except (OSError, wire.WireError) as e:
            self.events.log("dial_failed", addr=list(addr), error=str(e))
            return
        self._run_connection(sock, peer_id, addr, outgoing=True)

    # -- per-connection loop --------------------------------------------

    def _run_connection(self, sock: socket.socket, peer_id: bytes, addr, outgoing: bool):
        conn = PeerConn(sock, peer_id, addr, outgoing)
        with self._conns_lock:
            if conn.peer_key in self._conns:
                sock.close()
                return  # already connected to this peer
            self._conns[conn.peer_key] = conn
        self.events.log("peer_connected", peer=conn.peer_key[:8], addr=list(addr), outgoing=outgoing)

        try:
            bf = self.pm.bitfield_bytes()
            if any(bf):
                sock.sendall(wire.encode_message(wire.BITFIELD, bf))
            sock.sendall(wire.encode_message(wire.INTERESTED))
            conn.am_interested = True

            while not self._stop.is_set():
                try:
                    msg_id, payload = wire.recv_message(sock, timeout=SOCKET_POLL_TIMEOUT)
                except wire.WireTimeout:
                    msg_id, payload = None, b""  # nothing to read right now; fall through to scheduling
                except (wire.WireError, OSError):
                    # OSError covers the socket being closed out from under us
                    # by Node.stop() running concurrently on another thread.
                    break
                if msg_id is not None:
                    try:
                        self._handle_message(conn, msg_id, payload)
                    except wire.WireError:
                        # A malformed/out-of-range message from this peer —
                        # drop the connection cleanly instead of crashing
                        # the thread with an unhandled traceback.
                        break
                self._maybe_request_more(conn)
                self._maybe_retry_timeouts(conn)
                if self.pm.is_complete() and conn.am_interested:
                    conn.am_interested = False
                    try:
                        sock.sendall(wire.encode_message(wire.NOT_INTERESTED))
                    except OSError:
                        break
        except OSError:
            # The socket can be closed out from under this thread by
            # Node.stop() running concurrently — that's a normal shutdown
            # path, not a bug, so just fall through to teardown.
            pass
        finally:
            self._teardown_connection(conn)

    def _teardown_connection(self, conn: PeerConn):
        with self._conns_lock:
            self._conns.pop(conn.peer_key, None)
        self.choke_mgr.forget(conn.peer_key)
        self.pm.forget_peer(conn.peer_has)
        try:
            conn.sock.close()
        except OSError:
            pass
        self.events.log("peer_disconnected", peer=conn.peer_key[:8])

    # -- message handling -------------------------------------------------

    def _handle_message(self, conn: PeerConn, msg_id: int, payload: bytes):
        """Dispatch one parsed message, treating any parse/bounds failure
        as a protocol violation from an untrusted peer rather than letting
        it crash this connection's thread with an unhandled traceback.
        `struct.error` covers a too-short/malformed payload (e.g. a HAVE
        with a truncated 4-byte index); `IndexError`/`ValueError` cover an
        out-of-range piece index reaching the piece manager (both
        TorrentError and PieceError are ValueError subclasses).
        """
        try:
            self._dispatch_message(conn, msg_id, payload)
        except (struct.error, IndexError, ValueError) as e:
            self.events.log("protocol_violation", peer=conn.peer_key[:8],
                             msg=wire.message_name(msg_id), error=str(e))
            raise wire.WireError(f"protocol violation from peer: {e}") from e

    def _dispatch_message(self, conn: PeerConn, msg_id: int, payload: bytes):
        if msg_id == wire.CHOKE:
            conn.peer_choking = True
        elif msg_id == wire.UNCHOKE:
            conn.peer_choking = False
        elif msg_id == wire.INTERESTED:
            conn.peer_interested = True
            self.choke_mgr.set_interested(conn.peer_key, True)
        elif msg_id == wire.NOT_INTERESTED:
            conn.peer_interested = False
            self.choke_mgr.set_interested(conn.peer_key, False)
        elif msg_id == wire.HAVE:
            index = wire.unpack_have(payload)
            # Validate with the piece manager *before* recording it in
            # conn.peer_has — an out-of-range index must not get added to
            # peer state that teardown code will later iterate over.
            self.pm.note_peer_have(index)
            conn.peer_has.add(index)
        elif msg_id == wire.BITFIELD:
            indices = wire.bitfield_indices(payload, self.torrent.num_pieces)
            self.pm.note_peer_bitfield(indices)
            conn.peer_has |= indices
        elif msg_id == wire.REQUEST:
            self._handle_request(conn, payload)
        elif msg_id == wire.PIECE:
            self._handle_piece(conn, payload)
        elif msg_id == wire.CANCEL:
            pass  # simple pipeline depth makes cancel unnecessary to honor

    def _handle_request(self, conn: PeerConn, payload: bytes):
        index, begin, length = wire.unpack_request(payload)
        if conn.am_choking:
            return  # refuse to serve a choked peer, per protocol
        if not self.pm.has_piece(index):
            return
        try:
            block = self.pm.read_block(index, begin, length)
        except PieceError:
            return
        conn.sock.sendall(wire.encode_message(wire.PIECE, wire.pack_piece(index, begin, block)))
        self._uploaded_total += len(block)
        self.choke_mgr.record_upload(conn.peer_key, len(block))
        self.events.log("block_sent", peer=conn.peer_key[:8], index=index, begin=begin, length=len(block))

    def _handle_piece(self, conn: PeerConn, payload: bytes):
        index, begin, block = wire.unpack_piece(payload)
        conn.pending.pop((index, begin), None)
        self._downloaded_total += len(block)
        self.choke_mgr.record_download(conn.peer_key, len(block))
        try:
            completed = self.pm.receive_block(index, begin, block)
        except PieceError as e:
            self.events.log("piece_verify_failed", peer=conn.peer_key[:8], index=index, error=str(e))
            return
        self.events.log("block_received", peer=conn.peer_key[:8], index=index, begin=begin, length=len(block))
        if completed:
            self.events.log("piece_complete", index=index,
                             progress=list(self.pm.progress()))
            self._broadcast_have(index)
            if self.pm.is_complete():
                self.events.log("download_complete")
                try:
                    self._announce(event="completed")
                except Exception:
                    pass

    def _broadcast_have(self, index: int):
        msg = wire.encode_message(wire.HAVE, wire.pack_have(index))
        with self._conns_lock:
            conns = list(self._conns.values())
        for c in conns:
            try:
                c.sock.sendall(msg)
            except OSError:
                pass

    # -- request scheduling (rarest-first, pipelined) -----------------------

    def _maybe_request_more(self, conn: PeerConn):
        if conn.peer_choking or self.pm.is_complete():
            return
        with conn.lock:
            while len(conn.pending) < REQUEST_PIPELINE_DEPTH:
                target = self._pick_block_for(conn)
                if target is None:
                    return
                index, offset, length = target
                conn.pending[(index, offset)] = time.time()
                try:
                    conn.sock.sendall(
                        wire.encode_message(wire.REQUEST, wire.pack_request(index, offset, length))
                    )
                except OSError:
                    return

    def _maybe_retry_timeouts(self, conn: PeerConn):
        now = time.time()
        with conn.lock:
            stale = [k for k, t in conn.pending.items() if now - t > REQUEST_RETRY_TIMEOUT]
            for k in stale:
                del conn.pending[k]  # will be re-picked by _maybe_request_more

    def _pick_block_for(self, conn: PeerConn):
        """Pick the next (index, offset, length) block to request from this
        peer using rarest-first piece selection, then sequential blocks
        within that piece (blocks are cheap and unordered-safe; only piece
        *choice* needs the swarm-intelligence rarest-first policy).
        """
        index = self.pm.next_piece_rarest_first(conn.peer_has)
        if index is None:
            return None
        piece_len = self.torrent.piece_size(index)
        for offset, length in block_plan(piece_len):
            if (index, offset) in conn.pending:
                continue
            if self.pm.has_block(index, offset):
                continue
            return index, offset, length
        return None

    # -- choking loop ---------------------------------------------------

    def _choke_loop(self):
        while not self._stop.is_set():
            with self._conns_lock:
                conns = dict(self._conns)
            unchoked_ids = self.choke_mgr.decide_unchoked(conns.keys())
            for key, conn in conns.items():
                should_unchoke = key in unchoked_ids
                if should_unchoke and conn.am_choking:
                    conn.am_choking = False
                    try:
                        conn.sock.sendall(wire.encode_message(wire.UNCHOKE))
                        self.events.log("unchoke", peer=key[:8])
                    except OSError:
                        pass
                elif not should_unchoke and not conn.am_choking:
                    conn.am_choking = True
                    try:
                        conn.sock.sendall(wire.encode_message(wire.CHOKE))
                        self.events.log("choke", peer=key[:8])
                    except OSError:
                        pass
            self._stop.wait(self.choke_interval)

    # -- introspection ----------------------------------------------------

    def status(self):
        done, total = self.pm.progress()
        with self._conns_lock:
            n_conns = len(self._conns)
        return {
            "name": self.name,
            "pieces_done": done,
            "pieces_total": total,
            "complete": self.pm.is_complete(),
            "connections": n_conns,
            "uploaded": self._uploaded_total,
            "downloaded": self._downloaded_total,
        }
