"""A real gossip P2P network over TCP sockets between independent node
processes — no shared memory, no function calls between nodes. Messages
are newline-delimited JSON with hex-encoded binary payloads; deliberately
simple framing (this repo's earlier distributed builds, Concord's SSE
relay included, favor readable wire formats over binary efficiency) over
what has to be the real mechanism: inv/getdata-style announce-then-fetch
so a message only crosses the wire once per edge, and a seen-hash cache so
gossip doesn't loop forever on a graph with cycles.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..core.block import Block
from ..core.chain import Blockchain, ValidationError
from ..core.mempool import Mempool
from ..core.transaction import Transaction

MAX_SEEN_CACHE = 5000
RECV_BUFFER = 1 << 20


class PeerConnection:
    def __init__(self, sock: socket.socket, addr: Tuple[str, int], outbound: bool, peer_listen_port: Optional[int] = None):
        self.sock = sock
        self.addr = addr
        self.outbound = outbound
        self.peer_listen_port = peer_listen_port
        self.send_lock = threading.Lock()
        self.alive = True
        self._buf = b""

    def key(self) -> str:
        host = self.addr[0]
        port = self.peer_listen_port if self.peer_listen_port else self.addr[1]
        return f"{host}:{port}"

    def send(self, msg: dict) -> None:
        line = (json.dumps(msg) + "\n").encode("utf-8")
        with self.send_lock:
            try:
                self.sock.sendall(line)
            except OSError:
                self.alive = False

    def read_messages(self):
        """Generator yielding one parsed message dict at a time, blocking
        on the socket as needed. Ends (StopIteration) when the peer closes.
        """
        while True:
            while b"\n" not in self._buf:
                chunk = self.sock.recv(RECV_BUFFER)
                if not chunk:
                    return
                self._buf += chunk
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                yield json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue  # a hostile/garbled peer sends junk; skip, don't crash the node


@dataclass
class NetworkStats:
    blocks_received: int = 0
    blocks_relayed: int = 0
    txs_received: int = 0
    txs_relayed: int = 0
    blocks_rejected: int = 0


class P2PNode:
    def __init__(self, chain: Blockchain, mempool: Mempool, listen_host: str, listen_port: int,
                 node_name: str = "node"):
        self.chain = chain
        self.mempool = mempool
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.node_name = node_name

        self.peers: Dict[str, PeerConnection] = {}
        self.lock = threading.RLock()
        self.seen_blocks: "OrderedSeenSet" = OrderedSeenSet(MAX_SEEN_CACHE)
        self.seen_txs: "OrderedSeenSet" = OrderedSeenSet(MAX_SEEN_CACHE)
        self.stats = NetworkStats()

        self._server_sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []

        # Cut links to these peer keys, e.g. host:port strings, without
        # actually closing the socket underneath — this is what the
        # partition demo uses to simulate a real network split without
        # needing OS-level firewall rules.
        self.severed: Set[str] = set()

        self.on_new_tip: List[Callable[[bytes], None]] = []
        self.on_block_rejected: List[Callable[[str], None]] = []
        self.log: List[str] = []
        self._log_lock = threading.Lock()

    def _emit(self, msg: str) -> None:
        with self._log_lock:
            self.log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            if len(self.log) > 500:
                self.log = self.log[-500:]

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.listen_host, self.listen_port))
        self._server_sock.listen(16)
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()
        self._threads.append(t)
        self._emit(f"listening on {self.listen_host}:{self.listen_port}")

    def stop(self) -> None:
        self._stop.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        with self.lock:
            for peer in list(self.peers.values()):
                try:
                    peer.sock.close()
                except OSError:
                    pass

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                sock, addr = self._server_sock.accept()
            except OSError:
                return
            t = threading.Thread(target=self._handle_peer, args=(sock, addr, False), daemon=True)
            t.start()
            self._threads.append(t)

    def connect(self, host: str, port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        t = threading.Thread(target=self._handle_peer, args=(sock, (host, port), True), daemon=True)
        t.start()
        self._threads.append(t)

    # -- peer handling --------------------------------------------------------

    def _handle_peer(self, sock: socket.socket, addr, outbound: bool) -> None:
        conn = PeerConnection(sock, addr, outbound)
        try:
            conn.send({"type": "version", "listen_port": self.listen_port, "height": self.chain.height,
                       "tip": self.chain.tip_hash.hex(), "node": self.node_name})
            handshake_done = False
            for msg in conn.read_messages():
                if self._stop.is_set():
                    break
                if not handshake_done:
                    if msg.get("type") != "version":
                        return
                    conn.peer_listen_port = msg.get("listen_port")
                    with self.lock:
                        self.peers[conn.key()] = conn
                    self._emit(f"peer connected: {conn.key()} ({'out' if outbound else 'in'})")
                    handshake_done = True
                    self._maybe_sync(conn, msg.get("height", 0), msg.get("tip"))
                    continue
                self._dispatch(conn, msg)
        except (OSError, ConnectionError):
            pass
        finally:
            conn.alive = False
            with self.lock:
                if self.peers.get(conn.key()) is conn:
                    del self.peers[conn.key()]
            self._emit(f"peer disconnected: {conn.key()}")

    def _is_severed(self, peer_key: str) -> bool:
        return peer_key in self.severed or f"{self.node_name}|{peer_key}" in self.severed

    def sever(self, peer_key: str) -> None:
        """Simulate a network partition: stop sending to / accepting from
        this peer without tearing down the TCP connection, so healing the
        partition is just clearing this flag, exactly like real routers
        dropping and later restoring a link.
        """
        self.severed.add(peer_key)

    def heal(self, peer_key: str) -> None:
        self.severed.discard(peer_key)
        # A healed link doesn't get a fresh handshake (the TCP connection
        # never dropped), so nothing would otherwise re-trigger a sync —
        # ask explicitly, in both directions is handled by the peer doing
        # the same heal() call on its own side.
        self.request_sync(peer_key)

    def _send(self, conn: PeerConnection, msg: dict) -> None:
        if self._is_severed(conn.key()):
            return
        conn.send(msg)

    def broadcast(self, msg: dict, exclude: Optional[PeerConnection] = None) -> None:
        with self.lock:
            targets = [p for p in self.peers.values() if p is not exclude]
        for p in targets:
            self._send(p, msg)

    # -- sync -----------------------------------------------------------------

    def _maybe_sync(self, conn: PeerConnection, peer_height: int, peer_tip_hex: Optional[str]) -> None:
        # Always ask, even when the peer isn't taller: a partition can
        # leave two nodes at *equal* height on genuinely different chains
        # (equal cumulative work isn't even guaranteed, just equal block
        # count), and a height-only gate here means neither side ever
        # asks the other for anything — the exact case a fork-resolution
        # demo depends on. The request is cheap and self-limiting: a peer
        # with nothing new past `have` just replies with an empty batch.
        self._send(conn, {"type": "getblocks", "have": self.chain.tip_hash.hex()})

    def request_sync(self, peer_key: str) -> None:
        with self.lock:
            conn = self.peers.get(peer_key)
        if conn:
            self._send(conn, {"type": "getblocks", "have": self.chain.tip_hash.hex()})

    # -- message dispatch -------------------------------------------------------

    def _dispatch(self, conn: PeerConnection, msg: dict) -> None:
        if self._is_severed(conn.key()):
            return  # a severed peer's messages are dropped, like a real cut link
        mtype = msg.get("type")
        try:
            if mtype == "inv":
                self._on_inv(conn, msg)
            elif mtype == "getdata":
                self._on_getdata(conn, msg)
            elif mtype == "block":
                self._on_block(conn, msg)
            elif mtype == "tx":
                self._on_tx(conn, msg)
            elif mtype == "getblocks":
                self._on_getblocks(conn, msg)
            elif mtype == "blocks":
                self._on_blocks(conn, msg)
            elif mtype == "ping":
                self._send(conn, {"type": "pong"})
        except Exception:
            self._emit(f"error handling {mtype} from {conn.key()}: {traceback.format_exc()}")

    def _on_inv(self, conn: PeerConnection, msg: dict) -> None:
        kind, h = msg["kind"], bytes.fromhex(msg["hash"])
        known = self.chain.has_block(h) if kind == "block" else (h in self.mempool)
        seen = self.seen_blocks.contains(h) if kind == "block" else self.seen_txs.contains(h)
        if not known and not seen:
            self._send(conn, {"type": "getdata", "kind": kind, "hash": h.hex()})

    def _on_getdata(self, conn: PeerConnection, msg: dict) -> None:
        kind, h = msg["kind"], bytes.fromhex(msg["hash"])
        if kind == "block":
            blk = self.chain.get_block(h)
            if blk:
                self._send(conn, {"type": "block", "data": blk.serialize().hex()})
        elif kind == "tx":
            entry = self.mempool.entries.get(h)
            if entry:
                self._send(conn, {"type": "tx", "data": entry.tx.serialize().hex()})

    def _on_block(self, conn: PeerConnection, msg: dict) -> None:
        raw = bytes.fromhex(msg["data"])
        block = Block.deserialize(raw)
        self._ingest_block(block, conn)

    def _ingest_block(self, block: Block, source: Optional[PeerConnection]) -> bool:
        h = block.hash()
        # Blockchain/Mempool are plain (non-thread-safe) objects mutated
        # here from every peer's own reader thread, plus the miner thread
        # and RPC handler threads — without a lock, two peers delivering
        # competing blocks at once can interleave two `add_block` calls
        # (or a reorg with an orphan-triggered recursive one) and corrupt
        # `undo_log`/`active_chain`. Everything that reads or mutates
        # chain/mempool state for one block happens atomically under this
        # lock; only the (slow) PoW/script verification inside add_block
        # itself runs per-thread in real Bitcoin nodes too — a stronger
        # guarantee we trade away here in favor of this being simple and
        # obviously correct at the block counts this demo reaches.
        with self.lock:
            if self.seen_blocks.contains(h) or self.chain.has_block(h):
                return False
            self.seen_blocks.add(h)
            self.stats.blocks_received += 1
            try:
                tip_changed = self.chain.add_block(block)
            except ValidationError as e:
                self.stats.blocks_rejected += 1
                self._emit(f"REJECTED block {h.hex()[:12]} from {source.key() if source else 'self'}: {e}")
                for cb in self.on_block_rejected:
                    cb(str(e))
                return False

            if not self.chain.has_block(h):
                # add_block() buffered this as an orphan (its parent isn't
                # known yet) rather than applying or rejecting it — there
                # is nothing to announce or clean up yet. It'll be applied
                # (and *that* call will do all of this) once its parent
                # arrives and _accept_orphans_of() replays it.
                self._emit(f"buffered orphan block {h.hex()[:12]} (parent {block.header.prev_hash.hex()[:12]} unknown)")
                return False

            self._emit(f"accepted block {h.hex()[:12]} height={self.chain.meta[h].height} "
                        f"tip_changed={tip_changed}")
            confirmed_txids = [tx.txid() for tx in block.transactions[1:]]
            self.mempool.remove_confirmed(confirmed_txids)
            if tip_changed:
                self.mempool.revalidate()
                for cb in self.on_new_tip:
                    cb(self.chain.tip_hash)

            self.stats.blocks_relayed += 1

        self.broadcast({"type": "inv", "kind": "block", "hash": h.hex()}, exclude=source)
        return True

    def _on_tx(self, conn: PeerConnection, msg: dict) -> None:
        raw = bytes.fromhex(msg["data"])
        tx = Transaction.deserialize(raw)
        self._ingest_tx(tx, conn)

    def _ingest_tx(self, tx: Transaction, source: Optional[PeerConnection]) -> bool:
        txid = tx.txid()
        with self.lock:
            if self.seen_txs.contains(txid) or txid in self.mempool:
                return False
            self.seen_txs.add(txid)
            self.stats.txs_received += 1
            try:
                self.mempool.add_transaction(tx)
            except ValidationError as e:
                self._emit(f"rejected tx {txid.hex()[:12]}: {e}")
                return False
        self.stats.txs_relayed += 1
        self.broadcast({"type": "inv", "kind": "tx", "hash": txid.hex()}, exclude=source)
        return True

    def _on_getblocks(self, conn: PeerConnection, msg: dict) -> None:
        have = bytes.fromhex(msg["have"]) if msg.get("have") else None
        chain_hashes = self.chain.active_chain
        start_idx = 0
        # `have` being a block we know about (self.chain.meta) is not the
        # same as it being on *our active chain* — it can be a hash from
        # the peer's own competing fork, one we've validated and stored
        # as a side branch but never adopted. chain_hashes.index() would
        # raise ValueError in exactly that case (the case a partition-heal
        # sync depends on), so fall back to "send everything from genesis"
        # whenever `have` isn't actually in our active chain.
        if have is not None:
            for i, h in enumerate(chain_hashes):
                if h == have:
                    start_idx = i + 1
                    break
        missing = chain_hashes[start_idx:]
        MAX_BATCH = 500
        payload = [self.chain.blocks[h].serialize().hex() for h in missing[:MAX_BATCH]]
        self._send(conn, {"type": "blocks", "data": payload})

    def _on_blocks(self, conn: PeerConnection, msg: dict) -> None:
        for hexdata in msg["data"]:
            block = Block.deserialize(bytes.fromhex(hexdata))
            self._ingest_block(block, conn)
        if len(msg["data"]) > 0:
            # There may be more beyond this batch; ask again from our new tip.
            self._send(conn, {"type": "getblocks", "have": self.chain.tip_hash.hex()})

    # -- public submission API (used by miner / wallet / RPC) -----------------

    def submit_block(self, block: Block) -> bool:
        return self._ingest_block(block, source=None)

    def submit_tx(self, tx: Transaction) -> bool:
        return self._ingest_tx(tx, source=None)


class OrderedSeenSet:
    """A bounded FIFO-eviction hash cache (plain dict + deque would also
    work; this avoids importing collections just for one bounded set)."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._set: Set[bytes] = set()
        self._order: List[bytes] = []

    def contains(self, h: bytes) -> bool:
        return h in self._set

    def add(self, h: bytes) -> None:
        if h in self._set:
            return
        self._set.add(h)
        self._order.append(h)
        if len(self._order) > self.capacity:
            oldest = self._order.pop(0)
            self._set.discard(oldest)
