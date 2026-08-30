"""Block-explorer backend: a live, real multi-node network behind a stdlib
`http.server`, with zero blockchain logic duplicated in the browser — every
view the page renders is JSON this same `Blockchain`/`Node`/`SimNetwork`
code actually computed (same architecture as this repo's Gambit/Formulate/
Sift: the browser is a terminal, not a second implementation).

A background thread continuously round-robins mining attempts across a
small simulated network of nodes (real PoW search, real gossip with
latency, real fork resolution) so the explorer shows the network actually
converging live, not a canned recording. HTTP handlers only ever read
chain state or submit a transaction into the mempool — they never touch
consensus rules directly.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import block as blk
import blockchain as bc
import transaction as tx
from network import SimNetwork
from node import Node
from wallet import Wallet

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
NODE_NAMES = ["Ada", "Grace", "Katherine"]
NONCE_BUDGET = 1800
TICK_SLEEP = 0.35
FAUCET_AMOUNT = 20_00000000


class Network:
    """Shared, lock-protected state for the whole demo network + explorer."""

    def __init__(self, seed: int = 1234):
        burn_hash = b"\x00" * 20
        genesis_cb = tx.Transaction.coinbase(burn_hash, reward=bc.subsidy_at(0), height=0)
        gblock = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[genesis_cb],
                                target=bc.GENESIS_TARGET_DEFAULT, timestamp=1_700_000_000)
        gblock.mine()
        self.genesis = gblock
        self.net = SimNetwork(seed=seed, latency_range=(0.05, 0.6))
        self.nodes = {}
        for name in NODE_NAMES:
            chain = bc.Blockchain(gblock)
            self.nodes[name] = Node(name, chain, self.net, Wallet())
        self.lock = threading.RLock()
        self.log = deque(maxlen=500)
        self._last_ts = int(gblock.header.timestamp)
        self._running = False
        self._round_robin = list(NODE_NAMES)
        self._round_index = 0
        self._log_seq = 0
        self._add_log("network initialized: 3 nodes from the same genesis block")

    def _add_log(self, message: str) -> None:
        self._log_seq += 1
        self.log.append({"seq": self._log_seq, "t": time.time(), "message": message})

    def _next_timestamp(self) -> int:
        self._last_ts = max(int(time.time()), self._last_ts + 1)
        return self._last_ts

    def tick(self) -> None:
        with self.lock:
            name = self._round_robin[self._round_index]
            self._round_index = (self._round_index + 1) % len(self._round_robin)
            node = self.nodes[name]
            ts = self._next_timestamp()
            block = node.attempt_mine(NONCE_BUDGET, ts)
            if block is not None:
                self._add_log(f"{name} mined block #{node.chain.height()} {block.block_hash_hex()[:12]}")
            self.net.advance_to(self.net.now)
            # surface any fresh per-node log entries into the shared feed
            for n2 in self.nodes.values():
                while n2.log_cursor < len(n2.log):
                    self._add_log(f"[{n2.name}] {n2.log[n2.log_cursor]}")
                    n2.log_cursor += 1

    def faucet(self, node_name: str, to_address: str) -> tuple:
        with self.lock:
            node = self.nodes[node_name]
            try:
                t = node.wallet.create_transaction(node.chain.utxo_set(), to_address, FAUCET_AMOUNT, fee=1000)
            except Exception as e:  # noqa: BLE001 - surfaced to the caller as a clean API error
                return False, str(e)
            ok, reason = node.submit_transaction(t)
            if ok:
                self._add_log(f"[{node_name}] faucet sent {FAUCET_AMOUNT/1e8:.2f} coins -> {to_address[:14]}...")
            return ok, reason

    def send(self, node_name: str, to_address: str, amount: int, fee: int) -> tuple:
        with self.lock:
            node = self.nodes[node_name]
            try:
                t = node.wallet.create_transaction(node.chain.utxo_set(), to_address, amount, fee)
            except Exception as e:  # noqa: BLE001
                return False, str(e)
            ok, reason = node.submit_transaction(t)
            if ok:
                self._add_log(f"[{node_name}] sent {amount/1e8:.4f} coins -> {to_address[:14]}... (fee {fee})")
            return ok, reason

    def status(self) -> dict:
        with self.lock:
            out = {"names": NODE_NAMES, "nodes": {}}
            for name, node in self.nodes.items():
                out["nodes"][name] = {
                    "height": node.chain.height(),
                    "tip": node.chain.tip.hex(),
                    "work": node.chain.work[node.chain.tip],
                    "target": node.chain.blocks[node.chain.tip].header.target,
                    "mempool_size": len(node.mempool),
                    "address": node.wallet.address,
                    "balance": node.wallet.balance(node.chain.utxo_set()),
                    "blocks_mined": node.stats.blocks_mined,
                    "blocks_accepted_from_peers": node.stats.blocks_accepted_from_peers,
                    "blocks_rejected": node.stats.blocks_rejected,
                    "reorgs_seen": node.stats.reorgs_seen,
                }
            all_tips = {n["tip"] for n in out["nodes"].values()}
            out["converged"] = len(all_tips) == 1
            return out

    def chain_view(self, node_name: str) -> dict:
        with self.lock:
            node = self.nodes[node_name]
            hashes = node.chain.main_chain_hashes()
            blocks = []
            for h in reversed(hashes[-40:]):
                b = node.chain.blocks[h]
                blocks.append({
                    "hash": h.hex(),
                    "height": node.chain.heights[h],
                    "timestamp": b.header.timestamp,
                    "target": b.header.target,
                    "tx_count": len(b.transactions),
                    "prev_hash": b.header.prev_hash.hex(),
                    "nonce": b.header.nonce,
                })
            return {"blocks": blocks, "total_height": node.chain.height()}

    def block_detail(self, node_name: str, block_hash_hex: str) -> dict:
        with self.lock:
            node = self.nodes[node_name]
            h = bytes.fromhex(block_hash_hex)
            b = node.chain.blocks.get(h)
            if b is None:
                return None
            import merkle as mk
            leaves = [t.txid() for t in b.transactions]
            txs = []
            for i, t in enumerate(b.transactions):
                proof = mk.build_proof(leaves, i) if leaves else None
                proof_ok = proof.verify(b.header.merkle_root) if proof else False
                txs.append({
                    "txid": t.txid_hex(),
                    "is_coinbase": t.is_coinbase(),
                    "inputs": len(t.inputs),
                    "outputs": [{"amount": o.amount, "pubkey_hash": o.pubkey_hash.hex()} for o in t.outputs],
                    "total_output": t.total_output(),
                    "merkle_proof_len": len(proof.siblings) if proof else 0,
                    "merkle_proof_verifies": proof_ok,
                })
            return {
                "hash": h.hex(),
                "height": node.chain.heights.get(h),
                "prev_hash": b.header.prev_hash.hex(),
                "merkle_root": b.header.merkle_root.hex(),
                "timestamp": b.header.timestamp,
                "target": b.header.target,
                "nonce": b.header.nonce,
                "transactions": txs,
            }

    def mempool_view(self, node_name: str) -> dict:
        with self.lock:
            node = self.nodes[node_name]
            items = []
            for t in node.mempool.txs.values():
                items.append({"txid": t.txid_hex(), "outputs": len(t.outputs), "total": t.total_output()})
            return {"items": items}

    def recent_log(self, since_seq: int) -> list:
        with self.lock:
            return [e for e in self.log if e["seq"] > since_seq]


def mining_loop(network: Network, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        network.tick()
        time.sleep(TICK_SLEEP)


class Handler(BaseHTTPRequestHandler):
    network: Network = None  # set by serve()

    def log_message(self, fmt, *args):  # silence default stderr access log
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        net = self.network

        if path == "/" or path == "/index.html":
            return self._file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        if path == "/api/status":
            return self._json(net.status())
        if path == "/api/chain":
            name = qs.get("node", [NODE_NAMES[0]])[0]
            return self._json(net.chain_view(name))
        if path == "/api/block":
            name = qs.get("node", [NODE_NAMES[0]])[0]
            h = qs.get("hash", [""])[0]
            detail = net.block_detail(name, h)
            if detail is None:
                return self._json({"error": "not found"}, 404)
            return self._json(detail)
        if path == "/api/mempool":
            name = qs.get("node", [NODE_NAMES[0]])[0]
            return self._json(net.mempool_view(name))
        if path == "/api/events":
            since = int(qs.get("since", ["0"])[0])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                last_seq = since
                idle = 0
                while idle < 200:  # ~ a minute of idle keeps the handler thread from leaking forever
                    entries = net.recent_log(last_seq)
                    if entries:
                        idle = 0
                        for e in entries:
                            last_seq = e["seq"]
                            self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                        self.wfile.flush()
                    else:
                        idle += 1
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    time.sleep(0.3)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return self._json({"error": "invalid JSON body"}, 400)
        net = self.network

        if parsed.path == "/api/faucet":
            node = payload.get("node")
            to = payload.get("to_address")
            if node not in NODE_NAMES or not to:
                return self._json({"ok": False, "reason": "node and to_address are required"}, 400)
            ok, reason = net.faucet(node, to)
            return self._json({"ok": ok, "reason": reason})

        if parsed.path == "/api/send":
            node = payload.get("node")
            to = payload.get("to_address")
            amount = payload.get("amount")
            fee = payload.get("fee", 1000)
            if node not in NODE_NAMES or not to or not isinstance(amount, int) or amount <= 0:
                return self._json({"ok": False, "reason": "node, to_address, and a positive integer amount are required"}, 400)
            ok, reason = net.send(node, to, amount, int(fee))
            return self._json({"ok": ok, "reason": reason})

        return self._json({"error": "unknown endpoint"}, 404)


def serve(port: int = 8765, seed: int = 1234, host: str = "127.0.0.1") -> None:
    network = Network(seed=seed)
    Handler.network = network
    stop_event = threading.Event()
    miner_thread = threading.Thread(target=mining_loop, args=(network, stop_event), daemon=True)
    miner_thread.start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Genesis block explorer serving on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        httpd.shutdown()


if __name__ == "__main__":
    import sys
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    h = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    serve(port=p, host=h)
