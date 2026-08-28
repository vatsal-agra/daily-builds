"""A real peer-to-peer node: TCP sockets on localhost, a line-delimited
JSON gossip protocol, a background mining thread, and partition controls
so a demo (or a test) can split the network in two, let it fork, and
reconnect it to watch a real reorg happen.
"""
from __future__ import annotations

import json
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .block import Block, BlockHeader, mine_block
from .chain import BLOCK_REWARD, Blockchain
from .crypto import pubkey_to_address
from .mempool import Mempool
from .transaction import Transaction, make_coinbase
from .wallet import Wallet

Addr = Tuple[str, int]


def _recvlines(sock: socket.socket):
    buf = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                yield line


@dataclass
class PeerConn:
    addr: Addr
    sock: socket.socket
    send_lock: threading.Lock


class Node:
    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        genesis: Block,
        genesis_bits: int,
        wallet: Optional[Wallet] = None,
        mine: bool = True,
        max_tx_per_block: int = 50,
        log=None,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.addr: Addr = (host, port)
        self.genesis_bits = genesis_bits
        self.wallet = wallet or Wallet()
        self.mempool = Mempool()
        self.mine_enabled = mine
        self.max_tx_per_block = max_tx_per_block
        self.log = log or (lambda *a, **k: None)

        self.chain = Blockchain()
        ok, msg, _ = self.chain.add_block(genesis, genesis_bits)
        assert ok, f"genesis rejected: {msg}"

        self.peer_addrs: Set[Addr] = set()
        self.blocked_addrs: Set[Addr] = set()
        self.conns: Dict[Addr, PeerConn] = {}
        self.lock = threading.RLock()
        self._new_tip_event = threading.Event()
        self.running = False
        self._server_sock: Optional[socket.socket] = None
        self._threads: List[threading.Thread] = []
        self.blocks_mined = 0
        self.blocks_received = 0
        self.reorg_count = 0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.running = True
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(8)
        self._spawn(self._accept_loop)
        self._spawn(self._connector_loop)
        if self.mine_enabled:
            self._spawn(self._mining_loop)

    def stop(self) -> None:
        self.running = False
        self._new_tip_event.set()
        try:
            if self._server_sock:
                self._server_sock.close()
        except OSError:
            pass
        with self.lock:
            conns = list(self.conns.values())
        for c in conns:
            try:
                c.sock.close()
            except OSError:
                pass

    def _spawn(self, target) -> None:
        t = threading.Thread(target=target, daemon=True)
        t.start()
        self._threads.append(t)

    # ------------------------------------------------------------------
    # peer management / partitioning
    # ------------------------------------------------------------------
    def add_peer(self, addr: Addr) -> None:
        if addr != self.addr:
            self.peer_addrs.add(addr)

    def set_partition(self, blocked: Set[Addr]) -> None:
        """Simulate a network partition: block/unblock connections to the
        given addresses, closing any currently-open link to a newly-blocked
        peer so the split is immediate, not just "no new connections"."""
        with self.lock:
            self.blocked_addrs = set(blocked)
            for addr, conn in list(self.conns.items()):
                if addr in self.blocked_addrs:
                    try:
                        conn.sock.close()
                    except OSError:
                        pass
                    self.conns.pop(addr, None)
                    self.log(f"[{self.name}] partitioned from {addr}")

    def peer_count(self) -> int:
        with self.lock:
            return len(self.conns)

    def _connector_loop(self) -> None:
        while self.running:
            for addr in list(self.peer_addrs):
                if addr in self.blocked_addrs:
                    continue
                if addr <= self.addr:
                    # Deterministic dialing: of any two peers, only the one
                    # with the lower (host, port) address ever initiates —
                    # the other just accepts. Without this, both sides of a
                    # full mesh independently dial each other, and the two
                    # resulting sockets race to occupy the same `conns[addr]`
                    # slot; whichever loses gets silently overwritten and
                    # orphaned, leaving that link one-way (messages sent
                    # over the surviving socket in one direction were never
                    # actually paired with a live reader on it), which is
                    # exactly the missing-peer/dropped-broadcast bug this
                    # comment is here to stop from coming back.
                    continue
                with self.lock:
                    connected = addr in self.conns
                if connected:
                    continue
                try:
                    sock = socket.create_connection(addr, timeout=1)
                    self._register_conn(addr, sock)
                    self._spawn(lambda a=addr, s=sock: self._reader_loop(a, s))
                    self._send_to(addr, {"type": "get_chain"})
                    self._sync_mempool_to(addr)
                except OSError:
                    pass
            time.sleep(0.5)

    def _accept_loop(self) -> None:
        while self.running:
            try:
                sock, remote = self._server_sock.accept()
            except OSError:
                return
            # we don't know the *listening* port of an inbound peer from
            # accept() alone (it's an ephemeral client port), so the peer
            # identifies itself in its first message instead.
            self._spawn(lambda s=sock: self._inbound_handler(s))

    def _inbound_handler(self, sock: socket.socket) -> None:
        remote_addr: Optional[Addr] = None
        try:
            for line in _recvlines(sock):
                msg = json.loads(line.decode("utf-8"))
                if remote_addr is None:
                    hello = msg.get("from")
                    remote_addr = tuple(hello) if hello else None
                    if remote_addr:
                        if remote_addr in self.blocked_addrs:
                            sock.close()
                            return
                        self._register_conn(remote_addr, sock)
                        self._sync_mempool_to(remote_addr)
                self._handle_message(msg, sock)
        except (ConnectionError, OSError, json.JSONDecodeError):
            pass
        finally:
            if remote_addr:
                with self.lock:
                    if self.conns.get(remote_addr) and self.conns[remote_addr].sock is sock:
                        self.conns.pop(remote_addr, None)
            try:
                sock.close()
            except OSError:
                pass

    def _reader_loop(self, addr: Addr, sock: socket.socket) -> None:
        try:
            for line in _recvlines(sock):
                msg = json.loads(line.decode("utf-8"))
                self._handle_message(msg, sock)
        except (ConnectionError, OSError, json.JSONDecodeError):
            pass
        finally:
            with self.lock:
                if self.conns.get(addr) and self.conns[addr].sock is sock:
                    self.conns.pop(addr, None)
            try:
                sock.close()
            except OSError:
                pass

    def _register_conn(self, addr: Addr, sock: socket.socket) -> None:
        with self.lock:
            self.conns[addr] = PeerConn(addr=addr, sock=sock, send_lock=threading.Lock())

    # ------------------------------------------------------------------
    # wire protocol
    # ------------------------------------------------------------------
    def _send_to(self, addr: Addr, msg: dict) -> None:
        with self.lock:
            conn = self.conns.get(addr)
        if not conn:
            return
        msg = dict(msg)
        msg["from"] = list(self.addr)
        data = (json.dumps(msg) + "\n").encode("utf-8")
        try:
            with conn.send_lock:
                conn.sock.sendall(data)
        except OSError:
            pass

    def _sync_mempool_to(self, addr: Addr) -> None:
        """Announce every transaction we're currently holding to a
        newly-(re)established peer connection. A one-shot `_broadcast` at
        submit time isn't enough on its own: if it raced a connection that
        was mid-reconnect, the tx would otherwise be silently gone for
        good (nothing else ever re-announces it) — exactly the kind of gap
        real gossip networks close by syncing mempool state on connect."""
        with self.lock:
            txs = list(self.mempool.txs.values())
        for tx in txs:
            self._send_to(addr, {"type": "tx", "data": tx.to_dict()})

    def _broadcast(self, msg: dict, exclude: Optional[Addr] = None) -> None:
        with self.lock:
            addrs = list(self.conns.keys())
        for addr in addrs:
            if addr != exclude and addr not in self.blocked_addrs:
                self._send_to(addr, msg)

    def _handle_message(self, msg: dict, sock: socket.socket) -> None:
        mtype = msg.get("type")
        sender = tuple(msg["from"]) if msg.get("from") else None
        if mtype == "block":
            block = Block.from_dict(msg["data"])
            self._accept_block(block, source=sender)
        elif mtype == "tx":
            tx = Transaction.from_dict(msg["data"])
            self._accept_tx(tx, source=sender)
        elif mtype == "get_chain":
            with self.lock:
                hashes = self.chain.active_chain_hashes()
                blocks = [self.chain.blocks[h].to_dict() for h in hashes]
            if sender:
                self._send_to(sender, {"type": "chain", "data": blocks})
        elif mtype == "chain":
            blocks = [Block.from_dict(b) for b in msg["data"]]
            for block in blocks:
                self._accept_block(block, source=sender, rebroadcast=False)

    # ------------------------------------------------------------------
    # consensus actions
    # ------------------------------------------------------------------
    def _accept_block(self, block: Block, source: Optional[Addr], rebroadcast: bool = True) -> bool:
        with self.lock:
            old_tip = self.chain.tip
            accepted, message, reorg_info = self.chain.add_block(block, self.genesis_bits)
            if not accepted:
                if message.startswith("orphan") and source:
                    self._send_to(source, {"type": "get_chain"})
                return False
            self.blocks_received += 1
            if message == "already known":
                return True
            tip_changed = self.chain.tip != old_tip
            if reorg_info is not None:
                if message == "reorg":
                    self.reorg_count += 1
                for txid in reorg_info["connected_txids"]:
                    self.mempool.remove(txid)
                for tx in reorg_info["disconnected_txs"]:
                    self._readd_to_mempool_locked(tx)
            if tip_changed:
                self._new_tip_event.set()
        if rebroadcast:
            self._broadcast({"type": "block", "data": block.to_dict()}, exclude=source)
        return True

    def _readd_to_mempool_locked(self, tx: Transaction) -> None:
        """A transaction from a disconnected block goes back to the
        mempool only if it's still spendable against the new UTXO state
        (its inputs might have been double-spent by the winning branch)."""
        ok, fee, _ = self._check_tx_against_utxo(tx)
        if ok:
            self.mempool.add(tx, fee)

    def _check_tx_against_utxo(self, tx: Transaction) -> Tuple[bool, int, str]:
        ok, err = tx.verify_signatures()
        if not ok:
            return False, 0, err
        total_in = 0
        seen = set()
        for txin in tx.inputs:
            key = (txin.prev_txid, txin.prev_index)
            if key in seen:
                return False, 0, "duplicate input in transaction"
            seen.add(key)
            utxo = self.chain.utxo_set.get(key)
            if utxo is None:
                return False, 0, f"input {key} not in utxo set (spent or unknown)"
            if pubkey_to_address(bytes.fromhex(txin.pubkey)) != utxo["address"]:
                return False, 0, "pubkey does not own referenced utxo"
            total_in += utxo["amount"]
        total_out = tx.total_output()
        if total_in < total_out:
            return False, 0, "spends more than inputs provide"
        return True, total_in - total_out, ""

    def _accept_tx(self, tx: Transaction, source: Optional[Addr]) -> bool:
        with self.lock:
            if self.mempool.contains(tx.txid()):
                return True
            ok, fee, err = self._check_tx_against_utxo(tx)
            if not ok:
                self.log(f"[{self.name}] rejected tx {tx.txid()[:8]}: {err}")
                return False
            self.mempool.add(tx, fee)
        self._broadcast({"type": "tx", "data": tx.to_dict()}, exclude=source)
        return True

    def submit_transaction(self, tx: Transaction) -> Tuple[bool, str]:
        with self.lock:
            ok, fee, err = self._check_tx_against_utxo(tx)
            if not ok:
                return False, err
            self.mempool.add(tx, fee)
        self._broadcast({"type": "tx", "data": tx.to_dict()})
        return True, ""

    # ------------------------------------------------------------------
    # mining
    # ------------------------------------------------------------------
    def _mining_loop(self) -> None:
        while self.running:
            # Clear the "tip changed" flag BEFORE reading the tip we're
            # about to mine on, not after building the template. If a
            # peer's block landed between building the template and
            # mining it, clearing afterward would silently discard that
            # notification (the very thing `mine_block`'s stop_flag exists
            # to catch), leaving us mining for however long on a template
            # built from an already-stale parent — wasted work at best,
            # and at worst a needlessly deep, needlessly slow-to-resolve
            # fork if that stale block still finds a valid nonce before
            # this loop's next iteration would have replaced it anyway.
            self._new_tip_event.clear()
            with self.lock:
                tip = self.chain.tip
                height = self.chain.height() + 1
                bits = self.chain.calc_next_bits(tip, self.genesis_bits)
                selected = self.mempool.select_for_block(self.max_tx_per_block)
                total_fees = sum(self.mempool.fees.get(t.txid(), 0) for t in selected)
            coinbase = make_coinbase(
                self.wallet.address, BLOCK_REWARD + total_fees, height, random.randrange(1 << 30)
            )
            header = BlockHeader(
                version=1, prev_hash=tip, merkle_root_hex="", timestamp=time.time(),
                bits=bits, nonce=0, height=height,
            )
            block = Block(header=header, transactions=[coinbase] + selected)
            header.merkle_root_hex = block.compute_merkle_root()
            found = mine_block(block, stop_flag=lambda: self._new_tip_event.is_set() or not self.running)
            if not self.running:
                return
            if found:
                self.blocks_mined += 1
                accepted = self._accept_block(block, source=None)
                if accepted:
                    self.log(f"[{self.name}] mined block {block.hash_hex()[:10]} height={height}")

    # ------------------------------------------------------------------
    # introspection (used by CLI + explorer)
    # ------------------------------------------------------------------
    def status(self) -> dict:
        with self.lock:
            return {
                "name": self.name,
                "addr": f"{self.host}:{self.port}",
                "height": self.chain.height(),
                "tip": self.chain.tip,
                "peers": [f"{a[0]}:{a[1]}" for a in self.conns.keys()],
                "blocked": [f"{a[0]}:{a[1]}" for a in self.blocked_addrs],
                "mempool_size": len(self.mempool),
                "balance": self.chain.balance_of(self.wallet.address),
                "address": self.wallet.address,
                "blocks_mined": self.blocks_mined,
                "reorg_count": self.reorg_count,
                "cum_work": self.chain.cum_work.get(self.chain.tip, 0) if self.chain.tip else 0,
            }
