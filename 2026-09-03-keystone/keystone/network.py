"""A P2P node: a real TCP listen socket plus outbound connections to peers,
speaking a small INV/GETDATA-style gossip protocol so a block or
transaction only ever gets sent in full to a peer that doesn't already have
it, and every node independently relays anything new exactly once."""
from __future__ import annotations

import socket
import threading
import time

from . import wire
from .block import Block
from .transaction import Transaction
from .utxo import ValidationError


class Node:
    def __init__(self, host: str, port: int, chain, mempool, name: str = None):
        self.host = host
        self.port = port
        self.chain = chain
        self.mempool = mempool
        self.name = name or f"{host}:{port}"

        self.lock = threading.RLock()  # guards chain + mempool + peer/known-set mutation
        self.peers = {}  # (host, port) -> {"sock": socket, "send_lock": Lock, "height": int}
        self.known_blocks = set(chain.blocks.keys())
        self.known_txs = set()
        self.tx_store = {}  # txid -> Transaction, kept for GETDATA even after mempool eviction

        self._server_sock = None
        self._threads = []
        self.running = False

        self.blocks_received = 0
        self.txs_received = 0

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(16)
        self.running = True
        t = threading.Thread(target=self._accept_loop, daemon=True, name=f"{self.name}-accept")
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self.running = False
        try:
            if self._server_sock:
                self._server_sock.close()
        except OSError:
            pass
        with self.lock:
            peer_socks = [p["sock"] for p in self.peers.values()]
        for sock in peer_socks:
            try:
                sock.close()
            except OSError:
                pass

    def connect_to(self, host: str, port: int, timeout: float = 5.0) -> bool:
        if (host, port) in self.peers or (host == self.host and port == self.port):
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.settimeout(None)
        except OSError:
            return False
        self._register_peer(sock, (host, port))
        t = threading.Thread(target=self._peer_loop, args=(sock, (host, port)), daemon=True,
                              name=f"{self.name}->{host}:{port}")
        t.start()
        self._threads.append(t)
        self._send(sock, {"type": "version", "height": self.chain.height(), "port": self.port})
        return True

    # ------------------------------------------------------------------
    def _accept_loop(self) -> None:
        while self.running:
            try:
                sock, addr = self._server_sock.accept()
            except OSError:
                break
            peer_key = (addr[0], addr[1])  # provisional; corrected once we learn their listen port
            self._register_peer(sock, peer_key)
            t = threading.Thread(target=self._peer_loop, args=(sock, peer_key), daemon=True,
                                  name=f"{self.name}<-{addr}")
            t.start()
            self._threads.append(t)
            self._send(sock, {"type": "version", "height": self.chain.height(), "port": self.port})

    def _register_peer(self, sock: socket.socket, key) -> None:
        with self.lock:
            self.peers[key] = {"sock": sock, "send_lock": threading.Lock(), "height": 0}

    def _unregister_peer(self, key) -> None:
        with self.lock:
            self.peers.pop(key, None)

    def _send(self, sock: socket.socket, msg: dict) -> None:
        # find the peer entry owning this socket to use its send lock (a
        # socket must not be written to by two threads at once)
        with self.lock:
            entry = next((p for p in self.peers.values() if p["sock"] is sock), None)
        try:
            if entry is not None:
                with entry["send_lock"]:
                    wire.send_msg(sock, msg)
            else:
                wire.send_msg(sock, msg)
        except (OSError, wire.ConnectionClosed):
            pass

    def _peer_loop(self, sock: socket.socket, key) -> None:
        try:
            while self.running:
                try:
                    msg = wire.recv_msg(sock)
                except (wire.ConnectionClosed, OSError):
                    break  # real transport failure — the connection is done
                except ValueError:
                    break  # malformed frame (bad length/JSON) — can't recover mid-stream
                try:
                    self._dispatch(msg, sock, key)
                except (KeyError, TypeError, AttributeError, ValueError) as e:
                    # A single structurally-broken message (missing field,
                    # wrong type) from a misbehaving/malicious peer used to
                    # crash this whole reader thread with an uncaught
                    # exception — real Bitcoin-style hardening is to drop
                    # just the bad message (or the peer) cleanly, not spew a
                    # traceback. Found by adversarial review; see REVIEW.md.
                    _ = e
                    continue
        finally:
            self._unregister_peer(key)
            try:
                sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    def _dispatch(self, msg: dict, sock: socket.socket, key) -> None:
        mtype = msg.get("type")

        if mtype == "version":
            real_key = (key[0], msg.get("port", key[1]))
            with self.lock:
                if real_key != key and key in self.peers:
                    self.peers[real_key] = self.peers.pop(key)
                if real_key in self.peers:
                    self.peers[real_key]["height"] = msg.get("height", 0)
                my_height = self.chain.height()
            if msg.get("height", 0) > my_height:
                self._send(sock, {"type": "getchain", "from_height": my_height})

        elif mtype == "getchain":
            from_height = msg.get("from_height", 0)
            with self.lock:
                chain_blocks = self.chain.active_chain()
                blocks_to_send = [b.to_dict() for b in chain_blocks if b.height > from_height]
            self._send(sock, {"type": "chainblocks", "blocks": blocks_to_send})

        elif mtype == "chainblocks":
            for block_dict in msg.get("blocks", []):
                block = Block.from_dict(block_dict)
                self._receive_block(block, sock)

        elif mtype == "inv_block":
            h = msg.get("hash")
            with self.lock:
                have_it = h in self.known_blocks
            if not have_it:
                self._send(sock, {"type": "getdata_block", "hash": h})

        elif mtype == "inv_tx":
            txid = msg.get("txid")
            with self.lock:
                have_it = txid in self.known_txs
            if not have_it:
                self._send(sock, {"type": "getdata_tx", "txid": txid})

        elif mtype == "getdata_block":
            h = msg.get("hash")
            with self.lock:
                block = self.chain.get_block(h) or self.chain.orphans.get(h)
            if block is not None:
                self._send(sock, {"type": "block", "block": block.to_dict()})

        elif mtype == "getdata_tx":
            txid = msg.get("txid")
            with self.lock:
                tx = self.tx_store.get(txid)
            if tx is not None:
                self._send(sock, {"type": "tx", "tx": tx.to_dict()})

        elif mtype == "block":
            block = Block.from_dict(msg["block"])
            self._receive_block(block, sock)

        elif mtype == "tx":
            tx = Transaction.from_dict(msg["tx"])
            self._receive_tx(tx, sock)

    # ------------------------------------------------------------------
    def _receive_block(self, block: Block, from_sock) -> None:
        block_hash = block.hash()
        with self.lock:
            if block_hash in self.known_blocks:
                return
            result = self.chain.add_block(block, self.mempool)
            self.known_blocks.add(block_hash)
            self.blocks_received += 1

        if result["orphan"]:
            # ask the peer that sent us this orphan for its missing parent
            self._send(from_sock, {"type": "getdata_block", "hash": block.header.prev_hash})
            return
        if result["accepted"] and result["reason"] != "already known":
            self._relay(from_sock, {"type": "inv_block", "hash": block_hash})

    def _receive_tx(self, tx: Transaction, from_sock) -> None:
        txid = tx.txid()
        with self.lock:
            if txid in self.known_txs:
                return
            self.known_txs.add(txid)
            self.tx_store[txid] = tx
            try:
                accepted = self.mempool.try_add(tx, self.chain.utxo_set, self.chain.height())
            except ValidationError:
                accepted = False
            self.txs_received += 1
        if accepted:
            self._relay(from_sock, {"type": "inv_tx", "txid": txid})

    def _relay(self, exclude_sock, msg: dict) -> None:
        with self.lock:
            targets = [p["sock"] for p in self.peers.values() if p["sock"] is not exclude_sock]
        for sock in targets:
            self._send(sock, msg)

    # ------------------------------------------------------------------
    def announce_block(self, block: Block) -> None:
        """Called locally after this node mined (or was otherwise directly
        given) a block already applied to its own chain."""
        block_hash = block.hash()
        with self.lock:
            self.known_blocks.add(block_hash)
        self._relay(None, {"type": "inv_block", "hash": block_hash})

    def announce_tx(self, tx: Transaction) -> None:
        txid = tx.txid()
        with self.lock:
            self.known_txs.add(txid)
            self.tx_store[txid] = tx
        self._relay(None, {"type": "inv_tx", "txid": txid})

    def peer_count(self) -> int:
        with self.lock:
            return len(self.peers)

    @property
    def reorg_count(self) -> int:
        """Delegates to the chain's own authoritative counter — see the
        comment on Blockchain.total_reorgs for why a network-layer-only
        counter undercounts reorgs triggered via orphan resolution."""
        return self.chain.total_reorgs
