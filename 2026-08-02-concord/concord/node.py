"""A real P2P node: a TCP server plus outbound peer connections, a
flood-gossip protocol for blocks and transactions (inventory announce ->
fetch -> validate -> relay, with a seen-set so messages don't loop
forever), and full-chain sync (on connect, and whenever an inventory
announcement reveals we're missing more than the one new block) so a new
or lagging peer always catches up to the network's best chain instead of
silently forking away from it.

Wire format: each message is a 4-byte big-endian length prefix followed
by that many bytes of UTF-8 JSON. Every socket, every thread here is
real — no in-process shortcut stands in for the network.

Concurrency model for each (full-duplex) connection:
  - One dedicated reader thread does nothing but call recv and route:
    reply-shaped messages (chain_hashes/block/tx) go into a per-socket
    response queue; everything else (get_*/inv_*) is dispatched to a
    short-lived worker thread. Dispatch must never run on the reader
    thread itself — a handler like inv_block issues its own blocking
    get_chain_hashes/get_block requests on the same socket, and those
    replies can only be delivered by this connection's reader thread
    continuing to read while the handler waits; running the handler
    inline on the reader thread would deadlock the moment it tried to
    block on its own queue.
  - A per-socket lock serializes outbound writes (multiple worker
    threads on the same connection could otherwise interleave two
    messages' bytes on the wire).
  - A per-socket request lock ensures at most one request is in flight
    per connection, so a reply can never be delivered to the wrong
    waiter.
"""

import json
import queue
import socket
import struct
import threading
import time

from .block import Block
from .chain import Blockchain
from .mempool import Mempool, MempoolRejected
from .transaction import Transaction

RECV_TIMEOUT = 5.0
REQUEST_TIMEOUT = 10.0
RESPONSE_TYPES = {"chain_hashes", "block", "tx"}


def _frame(msg: dict) -> bytes:
    payload = json.dumps(msg).encode()
    return struct.pack(">I", len(payload)) + payload


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv_msg(sock):
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    (length,) = struct.unpack(">I", header)
    payload = _recv_exact(sock, length)
    if payload is None:
        return None
    return json.loads(payload.decode())


class _PeerConn:
    __slots__ = ("sock", "send_lock", "request_lock", "response_q")

    def __init__(self, sock):
        self.sock = sock
        self.send_lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.response_q = queue.Queue()


class Node:
    def __init__(self, host, port, chain: Blockchain, mempool: Mempool = None, name=None):
        self.host = host
        self.port = port
        self.chain = chain
        self.mempool = mempool if mempool is not None else Mempool()
        self.name = name or f"{host}:{port}"

        self.lock = threading.RLock()
        self.peers = {}   # (host, port) -> socket   (public: who we're connected to)
        self._conns = {}  # sock -> _PeerConn
        self._threads = []
        self._server_sock = None
        self.running = False

        self.seen_block_hashes = set()
        self.seen_tx_ids = set()

        self.events = []  # (timestamp, message) log for the demo/explorer
        self.on_event = None  # optional callback(str)

    # -- lifecycle ---------------------------------------------------------

    def _log(self, msg):
        entry = (time.time(), msg)
        with self.lock:
            self.events.append(entry)
            if len(self.events) > 500:
                self.events = self.events[-500:]
        if self.on_event:
            self.on_event(msg)

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(16)
        self.running = True
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()
        self._threads.append(t)
        self._log(f"listening on {self.host}:{self.port}")

    def stop(self):
        self.running = False
        with self.lock:
            socks = list(self.peers.values())
            self.peers.clear()
        for s in socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
        if self._server_sock:
            try:
                self._server_sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._server_sock.close()

    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self._server_sock.accept()
            except OSError:
                break
            sock.settimeout(RECV_TIMEOUT)
            conn = self._register_socket(sock)
            t = threading.Thread(target=self._reader_loop, args=(sock, conn, None), daemon=True)
            t.start()
            self._threads.append(t)

    def _register_socket(self, sock):
        conn = _PeerConn(sock)
        with self.lock:
            self._conns[sock] = conn
        return conn

    def _unregister_socket(self, sock):
        with self.lock:
            self._conns.pop(sock, None)

    def _send(self, sock, msg: dict):
        conn = self._conns.get(sock)
        data = _frame(msg)
        try:
            if conn is not None:
                with conn.send_lock:
                    sock.sendall(data)
            else:
                sock.sendall(data)
        except OSError:
            pass

    # -- connecting outward --------------------------------------------------

    def connect(self, host, port):
        addr = (host, port)
        with self.lock:
            if addr in self.peers:
                return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(RECV_TIMEOUT)
        sock.connect(addr)
        conn = self._register_socket(sock)
        self._send(sock, {"type": "hello", "port": self.port})
        with self.lock:
            self.peers[addr] = sock
        self._log(f"connected to {host}:{port}")
        t = threading.Thread(target=self._reader_loop, args=(sock, conn, addr), daemon=True)
        t.start()
        self._threads.append(t)
        self._sync_with_peer(sock)

    # -- the reader loop: read + route ONLY, never blocks on our own requests --

    def _reader_loop(self, sock, conn, addr):
        peer_addr = addr
        try:
            while self.running:
                try:
                    msg = _recv_msg(sock)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if msg is None:
                    break
                mtype = msg.get("type")
                if mtype == "hello" and peer_addr is None:
                    peer_addr = (sock.getpeername()[0], msg["port"])
                    with self.lock:
                        self.peers[peer_addr] = sock
                    self._log(f"accepted connection from {peer_addr[0]}:{peer_addr[1]}")
                    continue
                if mtype in RESPONSE_TYPES:
                    conn.response_q.put(msg)
                    continue
                # get_*/inv_* handlers may themselves block on this same
                # socket's request/response cycle — dispatch off-thread so
                # this loop keeps reading (and can deliver their replies)
                threading.Thread(target=self._handle_message, args=(sock, msg), daemon=True).start()
        finally:
            if peer_addr is not None:
                with self.lock:
                    if self.peers.get(peer_addr) is sock:
                        del self.peers[peer_addr]
            self._unregister_socket(sock)
            sock.close()

    def broadcast(self, msg, exclude_sock=None):
        with self.lock:
            targets = [s for s in self.peers.values() if s is not exclude_sock]
        for s in targets:
            self._send(s, msg)

    # -- request/response over a full-duplex socket ------------------------

    def _send_and_wait(self, sock, conn, msg, timeout=REQUEST_TIMEOUT):
        """Caller must already hold conn.request_lock."""
        self._send(sock, msg)
        try:
            return conn.response_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def _request(self, sock, msg, timeout=REQUEST_TIMEOUT):
        conn = self._conns.get(sock)
        if conn is None:
            return None
        with conn.request_lock:
            return self._send_and_wait(sock, conn, msg, timeout)

    # -- sync ------------------------------------------------------------

    def _sync_with_peer(self, sock):
        """Fetches the peer's full main-chain hash list, finds where it
        diverges from ours, and pulls every block we're missing — not just
        the newest one. This is what lets a node that's fallen behind by
        more than a single block (or forked away entirely) catch back up,
        rather than getting permanently stuck once a lone inv_block
        announcement isn't enough to bridge the gap."""
        conn = self._conns.get(sock)
        if conn is None:
            return
        with conn.request_lock:
            reply = self._send_and_wait(sock, conn, {"type": "get_chain_hashes"})
            if reply is None or reply.get("type") != "chain_hashes":
                return
            peer_hashes = reply["hashes"]
            with self.lock:
                our_hashes = self.chain.main_chain_hashes()
            divergence = 0
            for a, b in zip(our_hashes, peer_hashes):
                if a != b:
                    break
                divergence += 1
            missing = peer_hashes[divergence:]
            added = 0
            for h in missing:
                with self.lock:
                    if self.chain.has_block(h):
                        continue
                block_reply = self._send_and_wait(sock, conn, {"type": "get_block", "hash": h})
                if block_reply is None or block_reply.get("type") != "block" or not block_reply["block"]:
                    break
                block = Block.from_dict(block_reply["block"])
                with self.lock:
                    ok, became_tip, orphaned, reason = self.chain.add_block(block)
                    if ok:
                        added += 1
                        self.seen_block_hashes.add(block.hash())
                        if became_tip:
                            self.mempool.remove_confirmed(self.chain.main_chain_txids())
                            self.mempool.reintroduce(orphaned, self.chain.utxo)
                    else:
                        self._log(f"sync: rejected block {h[:10]}: {reason}")
                        break
        if added:
            with self.lock:
                new_height = self.chain.height()
            self._log(f"synced {added} block(s) from peer, now at height {new_height}")

    # -- message dispatch (always runs off the reader thread) ---------------

    def _handle_message(self, sock, msg):
        mtype = msg.get("type")

        if mtype == "get_chain_hashes":
            with self.lock:
                hashes = self.chain.main_chain_hashes()
            self._send(sock, {"type": "chain_hashes", "hashes": hashes})

        elif mtype == "get_block":
            with self.lock:
                block = self.chain.get_block(msg["hash"])
            self._send(sock, {"type": "block", "block": block.to_dict() if block else None})

        elif mtype == "get_tx":
            with self.lock:
                tx = self.mempool.transactions.get(msg["txid"])
            self._send(sock, {"type": "tx", "tx": tx.to_dict() if tx else None})

        elif mtype == "inv_block":
            h = msg["hash"]
            with self.lock:
                have_it = self.chain.has_block(h)
            if not have_it:
                with self.lock:
                    old_tip = self.chain.tip_hash
                self._sync_with_peer(sock)
                with self.lock:
                    new_tip = self.chain.tip_hash
                if new_tip != old_tip:
                    self.broadcast({"type": "inv_block", "hash": new_tip}, exclude_sock=sock)

        elif mtype == "inv_tx":
            txid = msg["txid"]
            with self.lock:
                known = txid in self.mempool or txid in self.seen_tx_ids
            if not known:
                tx_reply = self._request(sock, {"type": "get_tx", "txid": txid})
                if tx_reply and tx_reply.get("type") == "tx" and tx_reply["tx"]:
                    self._receive_transaction(Transaction.from_dict(tx_reply["tx"]), exclude_sock=sock)

    def _receive_block(self, block, exclude_sock=None):
        h = block.hash()
        with self.lock:
            ok, became_tip, orphaned, reason = self.chain.add_block(block)
            if ok:
                self.seen_block_hashes.add(h)
                if became_tip:
                    self.mempool.remove_confirmed(self.chain.main_chain_txids())
                    self.mempool.reintroduce(orphaned, self.chain.utxo)
        if ok:
            self._log(f"accepted block {h[:10]} height={block.height}"
                       + (" (new tip)" if became_tip else " (side branch)"))
            self.broadcast({"type": "inv_block", "hash": h}, exclude_sock=exclude_sock)
        else:
            self._log(f"rejected block {h[:10]}: {reason}")
        return ok, became_tip

    def _receive_transaction(self, tx, exclude_sock=None):
        txid = tx.txid()
        accepted = False
        with self.lock:
            try:
                self.mempool.add_transaction(tx, self.chain.utxo)
                self.seen_tx_ids.add(txid)
                accepted = True
            except MempoolRejected as e:
                self._log(f"rejected tx {txid[:10]}: {e}")
        if accepted:
            self.broadcast({"type": "inv_tx", "txid": txid}, exclude_sock=exclude_sock)
        return accepted

    # -- local actions -----------------------------------------------------

    def submit_transaction(self, tx):
        """Called locally (e.g. from a wallet) to inject a new transaction."""
        return self._receive_transaction(tx)

    def submit_block(self, block):
        """Called locally (e.g. after mining) to inject a newly found block."""
        return self._receive_block(block)
