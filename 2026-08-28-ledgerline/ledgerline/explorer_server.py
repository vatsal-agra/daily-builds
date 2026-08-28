"""A stdlib `http.server` backend for the block explorer. Same pattern as
this repo's other server-backed UIs (Gambit's chess board, Formulate's
spreadsheet, Impulse's physics sandbox): the browser holds zero chain
logic — every view and every action is a JSON round trip to real running
`Node` objects, so what you see is provably what the nodes believe."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List
from urllib.parse import parse_qs, urlparse

from .network import apply_partition_groups
from .transaction import Transaction
from .wallet import InsufficientFunds

STATIC_DIR = Path(__file__).parent / "static"


def make_handler(nodes: List, log_fn=None):
    by_name = {n.name: n for n in nodes}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if log_fn:
                log_fn("[http] " + (fmt % args))

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str):
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path in ("/", "/index.html"):
                return self._send_file(STATIC_DIR / "explorer.html", "text/html; charset=utf-8")
            if parsed.path == "/api/status":
                return self._send_json({"nodes": [n.status() for n in nodes]})
            if parsed.path == "/api/chain":
                node = by_name.get(qs.get("node", [""])[0])
                if not node:
                    return self._send_json({"error": "unknown node"}, 404)
                with node.lock:
                    hashes = node.chain.active_chain_hashes()
                    blocks = []
                    for h in hashes:
                        d = node.chain.blocks[h].to_dict()
                        d["hash"] = h
                        blocks.append(d)
                return self._send_json({"blocks": blocks})
            if parsed.path == "/api/mempool":
                node = by_name.get(qs.get("node", [""])[0])
                if not node:
                    return self._send_json({"error": "unknown node"}, 404)
                with node.lock:
                    snap = node.mempool.snapshot()
                return self._send_json({"txs": snap})
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                return self._send_json({"ok": False, "error": "malformed JSON body"}, 400)

            parsed = urlparse(self.path)
            if parsed.path == "/api/send":
                return self._handle_send(payload)
            if parsed.path == "/api/partition":
                return self._handle_partition(payload)
            self.send_response(404)
            self.end_headers()

        def _handle_send(self, payload):
            node = by_name.get(payload.get("from"))
            to_addr = payload.get("to", "")
            try:
                amount = int(payload.get("amount"))
                fee = int(payload.get("fee", 1))
            except (TypeError, ValueError):
                return self._send_json({"ok": False, "error": "amount/fee must be integers"})
            if not node:
                return self._send_json({"ok": False, "error": "unknown sender node"})
            if not to_addr:
                return self._send_json({"ok": False, "error": "missing recipient address"})
            if amount <= 0:
                return self._send_json({"ok": False, "error": "amount must be positive"})
            if fee < 0:
                return self._send_json({"ok": False, "error": "fee cannot be negative"})
            try:
                with node.lock:
                    tx: Transaction = node.wallet.create_transaction(
                        node.chain, to_addr, amount, fee, mempool=node.mempool
                    )
            except InsufficientFunds as exc:
                return self._send_json({"ok": False, "error": str(exc)})
            except Exception as exc:  # malformed address, etc. -> clean error, never a 500
                return self._send_json({"ok": False, "error": f"could not build transaction: {exc}"})
            ok, err = node.submit_transaction(tx)
            if not ok:
                return self._send_json({"ok": False, "error": err})
            return self._send_json({"ok": True, "txid": tx.txid()})

        def _handle_partition(self, payload):
            groups = payload.get("groups")
            if not isinstance(groups, list):
                return self._send_json({"ok": False, "error": "'groups' must be a list of name-lists"})
            try:
                apply_partition_groups(nodes, groups)
            except Exception as exc:
                return self._send_json({"ok": False, "error": str(exc)})
            return self._send_json({"ok": True})

    return Handler


def run_explorer(nodes: List, host: str = "127.0.0.1", port: int = 8765, log_fn=None) -> ThreadingHTTPServer:
    handler = make_handler(nodes, log_fn=log_fn)
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
