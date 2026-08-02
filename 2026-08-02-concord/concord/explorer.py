"""Server-backed JSON API for a node, plus static file serving for the
block-explorer UI. Zero blockchain logic lives client-side — every view
(chain, block detail, Merkle proof, mempool, peers) is a real query
against this node's live chain/mempool state."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

from .merkle import merkle_proof, sha256d
from .transaction import Transaction

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def _block_summary(block, block_hash):
    return {
        "hash": block_hash,
        "height": block.height,
        "prev_hash": block.prev_hash,
        "timestamp": block.timestamp,
        "nonce": block.nonce,
        "target": block.target,
        "tx_count": len(block.transactions),
        "merkle_root": block.merkle_root_hex,
    }


def _tx_summary(tx):
    return {
        "txid": tx.txid(),
        "is_coinbase": tx.is_coinbase,
        "n_inputs": len(tx.inputs),
        "n_outputs": len(tx.outputs),
        "total_output": tx.total_output(),
        "outputs": [o.to_dict() for o in tx.outputs],
        "inputs": [{"txid": i.txid, "index": i.index} for i in tx.inputs],
    }


def make_handler(node):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep test/demo output clean; node.events already logs

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path, content_type):
            full = os.path.join(WEB_DIR, path)
            if not os.path.abspath(full).startswith(os.path.abspath(WEB_DIR)) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/" or path == "/index.html":
                return self._file("index.html", "text/html; charset=utf-8")

            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return

            if not path.startswith("/api/"):
                self.send_error(404)
                return

            with node.lock:
                if path == "/api/status":
                    return self._json({
                        "name": node.name,
                        "height": node.chain.height(),
                        "tip": node.chain.tip_hash,
                        "difficulty": node.chain.blocks_by_hash[node.chain.tip_hash].target,
                        "peer_count": len(node.peers),
                        "mempool_size": len(node.mempool),
                    })

                if path == "/api/chain":
                    hashes = node.chain.main_chain_hashes()
                    return self._json([
                        _block_summary(node.chain.blocks_by_hash[h], h) for h in hashes
                    ])

                if path.startswith("/api/block/") and "/proof/" not in path:
                    h = unquote(path[len("/api/block/"):])
                    block = node.chain.get_block(h)
                    if block is None:
                        return self._json({"error": "not found"}, 404)
                    return self._json({
                        "summary": _block_summary(block, h),
                        "transactions": [_tx_summary(tx) for tx in block.transactions],
                    })

                if path.startswith("/api/block/") and "/proof/" in path:
                    rest = path[len("/api/block/"):]
                    h, txid = rest.split("/proof/")
                    h, txid = unquote(h), unquote(txid)
                    block = node.chain.get_block(h)
                    if block is None:
                        return self._json({"error": "block not found"}, 404)
                    leaves = [bytes.fromhex(tx.txid()) for tx in block.transactions]
                    ids = [tx.txid() for tx in block.transactions]
                    if txid not in ids:
                        return self._json({"error": "tx not in block"}, 404)
                    idx = ids.index(txid)
                    proof = merkle_proof(leaves, idx)
                    return self._json({
                        "leaf": leaves[idx].hex(),
                        "root": block.merkle_root_hex,
                        "steps": [{"sibling": s.hex(), "is_right": r} for s, r in proof],
                    })

                if path == "/api/mempool":
                    return self._json([_tx_summary(tx) for tx in node.mempool.transactions.values()])

                if path.startswith("/api/tx/"):
                    txid = unquote(path[len("/api/tx/"):])
                    tx = node.mempool.transactions.get(txid)
                    location = "mempool"
                    if tx is None:
                        for h in reversed(node.chain.main_chain_hashes()):
                            block = node.chain.blocks_by_hash[h]
                            for t in block.transactions:
                                if t.txid() == txid:
                                    tx, location = t, f"block {block.height}"
                                    break
                            if tx:
                                break
                    if tx is None:
                        return self._json({"error": "not found"}, 404)
                    return self._json({"location": location, **_tx_summary(tx)})

                if path.startswith("/api/utxo/"):
                    address = unquote(path[len("/api/utxo/"):])
                    utxos = [
                        {"txid": txid, "index": idx, "amount": out.amount}
                        for (txid, idx), out in node.chain.utxo.items()
                        if out.address == address
                    ]
                    balance = sum(u["amount"] for u in utxos)
                    return self._json({"address": address, "balance": balance, "utxos": utxos})

                if path == "/api/peers":
                    return self._json([f"{h}:{p}" for (h, p) in node.peers.keys()])

                if path == "/api/events":
                    return self._json([{"t": t, "msg": m} for t, m in node.events[-100:]])

            self.send_error(404)

        def do_POST(self):
            if self.path != "/api/submit_tx":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                tx = Transaction.from_dict(data)
            except (ValueError, KeyError) as e:
                return self._json({"error": f"malformed transaction: {e}"}, 400)
            accepted = node.submit_transaction(tx)
            if accepted:
                return self._json({"accepted": True, "txid": tx.txid()})
            return self._json({"accepted": False, "error": "rejected by mempool"}, 400)

    return Handler


class ExplorerServer:
    def __init__(self, node, host="127.0.0.1", port=0):
        self.node = node
        self._httpd = ThreadingHTTPServer((host, port), make_handler(node))
        self.host, self.port = self._httpd.server_address
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
