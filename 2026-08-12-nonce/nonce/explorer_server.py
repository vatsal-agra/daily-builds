"""A live block-explorer web server: a real multi-node network mines,
transacts, forks, and reorgs in a background thread; a stdlib
http.server backend exposes its actual state as JSON; explorer.html
polls it and renders — zero client-side ledger logic, same "server holds
all truth, browser just displays it" pattern as this repo's past
server-backed UIs (Formulate, Gambit).
"""

import copy
import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .wallet import Wallet
from .core.blockchain import Blockchain, create_genesis, subsidy_at
from .network.bus import Bus
from .network.node import Node

NODE_NAMES = ["N1", "N2", "N3", "N4", "N5"]
HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "explorer.html")


class Simulation:
    def __init__(self, num_nodes=3, seed=42):
        num_nodes = max(2, min(num_nodes, len(NODE_NAMES)))
        self.lock = threading.RLock()
        self.rng = random.Random(seed)
        self.tick = 0
        self.running = True
        self.partitioned = False
        self.events = []  # list of {"tick", "text"} newest last

        self.wallets = {name: Wallet() for name in NODE_NAMES[:num_nodes]}
        first = NODE_NAMES[0]
        genesis = create_genesis(self.wallets[first].address)
        self.bus = Bus(seed=seed)
        self.nodes = {}
        for name in NODE_NAMES[:num_nodes]:
            chain = Blockchain(copy.deepcopy(genesis))
            self.nodes[name] = Node(name, chain, self.bus, wallet=self.wallets[name])
        self.node_names = list(self.nodes.keys())
        self._log(f"network started with {num_nodes} nodes, genesis {genesis.hash().hex()[:12]}")

    def _log(self, text):
        self.events.append({"tick": self.tick, "text": text})
        self.events = self.events[-200:]

    def step(self):
        with self.lock:
            self.tick += 1
            miner_name = self.node_names[self.tick % len(self.node_names)]
            miner = self.nodes[miner_name]

            # occasionally send a payment between two random funded wallets first,
            # so the block the miner is about to produce has something to include
            if self.rng.random() < 0.5:
                self._maybe_send_payment(miner)

            block = miner.mine_block()
            self._log(f"{miner_name} mined block {block.hash().hex()[:10]} "
                      f"(height {block.height}, {len(block.transactions)} tx)")

            # periodically demonstrate a partition -> fork -> heal -> reorg cycle
            if self.tick % 14 == 0 and not self.partitioned and len(self.node_names) >= 3:
                self._start_partition()
            elif self.partitioned and self.tick % 14 == 6:
                self._heal_partition()

    def _maybe_send_payment(self, spender_node):
        wallet = spender_node.wallet
        balance = spender_node.chain.balance(wallet.address)
        if balance < 2_00000000:
            return
        others = [n for n in self.node_names if n != spender_node.id]
        if not others:
            return
        recipient = self.wallets[self.rng.choice(others)]
        amount = self.rng.randint(1_00000000, max(1_00000000, balance // 4))
        try:
            tx = wallet.build_transaction(spender_node.chain, recipient.address, amount, fee=1000)
        except Exception:
            return
        spender_node.submit_transaction(tx)
        self._log(f"{spender_node.id} sent {amount / 1e8:.2f} NCE to {recipient.address[:10]}…")

    def _start_partition(self):
        half = len(self.node_names) // 2
        group_a = set(self.node_names[:half])
        group_b = set(self.node_names[half:])
        self.bus.partition([group_a, group_b])
        self.partitioned = True
        self._log(f"NETWORK PARTITIONED: {sorted(group_a)} vs {sorted(group_b)}")

    def _heal_partition(self):
        self.bus.heal()
        self.bus.resync_all()
        self.partitioned = False
        tips = {n.chain.tip_hash for n in self.nodes.values()}
        converged = len(tips) == 1
        self._log(f"partition healed, resynced — {'all nodes converged' if converged else 'STILL DIVERGENT'} "
                  f"at height {max(n.chain.height() for n in self.nodes.values())}")

    def snapshot(self):
        with self.lock:
            any_node = next(iter(self.nodes.values()))
            tip_counts = {}
            for n in self.nodes.values():
                tip_counts[n.chain.tip_hash] = tip_counts.get(n.chain.tip_hash, 0) + 1
            majority_tip = max(tip_counts, key=tip_counts.get)
            majority_chain = self.nodes[next(iter(self.nodes))].chain
            for n in self.nodes.values():
                if n.chain.tip_hash == majority_tip:
                    majority_chain = n.chain
                    break

            chain_hashes = majority_chain.chain_to_genesis(majority_tip)[-15:]
            blocks = []
            for h in reversed(chain_hashes):
                b = majority_chain.blocks[h]
                blocks.append({
                    "height": b.height,
                    "hash": h.hex(),
                    "prev_hash": b.header.prev_hash.hex(),
                    "timestamp": b.header.timestamp,
                    "bits": f"{b.header.bits:#010x}",
                    "nonce": b.header.nonce,
                    "tx_count": len(b.transactions),
                    "txs": [{
                        "txid": tx.txid().hex(),
                        "coinbase": tx.is_coinbase(),
                        "inputs": len(tx.inputs),
                        "outputs": [{"amount": o.amount, "to": o.to_address} for o in tx.outputs],
                    } for tx in b.transactions],
                })

            nodes = []
            for name, n in self.nodes.items():
                nodes.append({
                    "id": name,
                    "address": n.wallet.address if n.wallet else None,
                    "height": n.chain.height(),
                    "tip": n.chain.tip_hash.hex(),
                    "balance": n.chain.balance(n.wallet.address) if n.wallet else 0,
                    "mempool": len(n.mempool),
                    "on_majority_chain": n.chain.tip_hash == majority_tip,
                })

            total_supply = sum(o.amount for o in majority_chain.utxo_set.values())

            return {
                "tick": self.tick,
                "partitioned": self.partitioned,
                "nodes": nodes,
                "blocks": blocks,
                "events": list(reversed(self.events[-40:])),
                "total_supply": total_supply,
                "difficulty_bits": f"{majority_chain.blocks[majority_tip].header.bits:#010x}",
            }


def run_explorer(host="127.0.0.1", port=8420, num_nodes=3, tick_interval=0.35):
    sim = Simulation(num_nodes=num_nodes)

    def loop():
        while sim.running:
            try:
                sim.step()
            except Exception as exc:  # a background sim hiccup shouldn't kill the server
                sim._log(f"[sim error] {exc!r}")
            time.sleep(tick_interval)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "explorer.html"))
    with open(html_path, "rb") as f:
        html_bytes = f.read()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep stdout clean; sim._log already narrates what matters

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, html_bytes, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                body = json.dumps(sim.snapshot()).encode()
                self._send(200, body, "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def _send(self, code, body, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Nonce explorer running at http://{host}:{port}  ({num_nodes} nodes, ~{1/tick_interval:.1f} blocks/sec)")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sim.running = False
        server.shutdown()
