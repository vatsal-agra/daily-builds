"""A real peer-to-peer gossip network: each NetworkNode is a TCP server +
client wrapping a bedrock.node.Node. Blocks and transactions are flooded to
peers (with a seen-cache so gossip doesn't loop forever); a newly connected
peer requests the other side's full chain so it can catch up.

Wire format: newline-delimited JSON over a persistent TCP connection per
peer. Deliberately simple (no compact block relay, no inv/getdata
two-phase handshake) — the point demonstrated here is real independent
processes converging on one chain via a real network protocol, not
production block-relay efficiency.
"""

import json
import socket
import threading
import time

from bedrock.block import Block
from bedrock.chain import ChainError
from bedrock.mempool import MempoolError
from bedrock.transaction import Transaction


class Peer:
    def __init__(self, sock: socket.socket, address):
        self.sock = sock
        self.address = address
        self._send_lock = threading.Lock()

    def send(self, msg: dict) -> None:
        line = (json.dumps(msg) + "\n").encode("utf-8")
        with self._send_lock:
            self.sock.sendall(line)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class NetworkNode:
    def __init__(self, node, host: str = "127.0.0.1", port: int = 0, log=None):
        self.node = node
        self.host = host
        self.port = port
        self._log = log or (lambda *a: None)
        self.server_sock = None
        self.peers = {}          # (host, advertised_port) -> Peer
        self.seen_blocks = set()
        self.seen_txs = set()
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._threads = []

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> int:
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(16)
        self.port = self.server_sock.getsockname()[1]
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()
        self._threads.append(t)
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass
        with self.lock:
            peers = list(self.peers.values())
        for peer in peers:
            peer.close()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.server_sock.settimeout(0.5)
                sock, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            peer = Peer(sock, addr)
            with self.lock:
                self.peers[addr] = peer
            t = threading.Thread(target=self._peer_read_loop, args=(peer,), daemon=True)
            t.start()
            self._threads.append(t)

    def connect(self, host: str, port: int, timeout: float = 5.0) -> Peer:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.settimeout(None)
        peer = Peer(sock, (host, port))
        with self.lock:
            self.peers[(host, port)] = peer
        t = threading.Thread(target=self._peer_read_loop, args=(peer,), daemon=True)
        t.start()
        self._threads.append(t)
        peer.send({"type": "hello", "port": self.port})
        peer.send({"type": "get_chain"})
        return peer

    # -- message handling -------------------------------------------------

    def _peer_read_loop(self, peer: Peer) -> None:
        try:
            f = peer.sock.makefile("r", encoding="utf-8")
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._handle_message(peer, msg)
        except (OSError, ConnectionError):
            pass
        finally:
            with self.lock:
                for key in [k for k, v in self.peers.items() if v is peer]:
                    del self.peers[key]
            peer.close()

    def _handle_message(self, peer: Peer, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "hello":
            self._rekey_peer(peer, msg.get("port"))
        elif mtype == "get_chain":
            self._send_chain(peer)
        elif mtype == "chain":
            for raw_hex in msg.get("data", []):
                self._ingest_block(Block.from_wire_hex(raw_hex), from_peer=peer, relay=False)
        elif mtype == "block":
            self._ingest_block(Block.from_wire_hex(msg["data"]), from_peer=peer, relay=True)
        elif mtype == "tx":
            tx, _ = Transaction.from_bytes(bytes.fromhex(msg["data"]))
            self._ingest_tx(tx, from_peer=peer, relay=True)

    def _rekey_peer(self, peer: Peer, advertised_port) -> None:
        if not advertised_port:
            return
        with self.lock:
            for key in [k for k, v in self.peers.items() if v is peer]:
                del self.peers[key]
            self.peers[(peer.address[0], advertised_port)] = peer

    def _send_chain(self, peer: Peer) -> None:
        with self.lock:
            path = self.node.chain.path_from_genesis(self.node.chain.tip_hash)
            blocks_hex = [self.node.chain.get_block(h).to_bytes().hex() for h in path]
        peer.send({"type": "chain", "data": blocks_hex})

    def _ingest_block(self, block: Block, from_peer: Peer = None, relay: bool = True) -> str:
        with self.lock:
            if block.hash in self.seen_blocks:
                return "duplicate"
            self.seen_blocks.add(block.hash)
            try:
                status = self.node.submit_block(block)
            except ChainError as exc:
                self._log(f"rejected block {block.hash[:12]}: {exc}")
                return "rejected"
        self._log(f"block {block.hash[:12]} height={self.node.chain.height} status={status}")
        if relay and status != "duplicate":
            self._broadcast({"type": "block", "data": block.to_bytes().hex()}, exclude=from_peer)
        if status == "orphan" and from_peer is not None:
            from_peer.send({"type": "get_chain"})
        return status

    def _ingest_tx(self, tx: Transaction, from_peer: Peer = None, relay: bool = True) -> bool:
        with self.lock:
            if tx.txid in self.seen_txs:
                return False
            self.seen_txs.add(tx.txid)
            try:
                self.node.submit_transaction(tx)
            except (ChainError, MempoolError) as exc:
                self._log(f"rejected tx {tx.txid[:12]}: {exc}")
                return False
        if relay:
            self._broadcast({"type": "tx", "data": tx.to_bytes().hex()}, exclude=from_peer)
        return True

    def _broadcast(self, msg: dict, exclude: Peer = None) -> None:
        with self.lock:
            peers = list(self.peers.values())
        for peer in peers:
            if peer is exclude:
                continue
            try:
                peer.send(msg)
            except OSError:
                pass

    # -- local announcements (this node produced the block/tx itself) -------

    def announce_block(self, block: Block) -> None:
        with self.lock:
            self.seen_blocks.add(block.hash)
        self._broadcast({"type": "block", "data": block.to_bytes().hex()})

    def announce_tx(self, tx: Transaction) -> None:
        with self.lock:
            self.seen_txs.add(tx.txid)
        self._broadcast({"type": "tx", "data": tx.to_bytes().hex()})

    def peer_count(self) -> int:
        with self.lock:
            return len(self.peers)


def wait_until_converged(net_nodes: list, timeout: float = 10.0, poll: float = 0.05) -> bool:
    """Test/demo helper: block until every node in `net_nodes` has the same
    chain tip hash, or return False on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        tips = {nn.node.chain.tip_hash for nn in net_nodes}
        if len(tips) == 1:
            return True
        time.sleep(poll)
    return False
