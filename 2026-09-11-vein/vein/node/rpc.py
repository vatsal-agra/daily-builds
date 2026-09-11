"""A small JSON-over-HTTP control/query API for one node — stdlib
`http.server` only, no Flask. Used by the CLI wallet, the demo scripts,
and the block-explorer visualizer (which gets a real live SSE event
stream, not a poll-and-diff hack).
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from ..core.block import Block
from ..core.chain import ValidationError
from ..core.transaction import Transaction
from ..crypto.address import pubkey_hash_from_address, is_valid_address


class RPCServer:
    def __init__(self, node, chain, mempool, miner, host: str, port: int):
        self.node = node
        self.chain = chain
        self.mempool = mempool
        self.miner = miner
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._event_subscribers: list[queue.Queue] = []
        self._sub_lock = threading.Lock()

        node.on_new_tip.append(lambda tip: self._publish({"type": "new_tip", "hash": tip.hex(),
                                                            "height": chain.height}))

    def publish_tx_event(self, tx: Transaction) -> None:
        self._publish({"type": "new_tx", "txid": tx.txid().hex()})

    def _publish(self, event: dict) -> None:
        with self._sub_lock:
            subs = list(self._event_subscribers)
        for q in subs:
            q.put(event)

    def start(self) -> None:
        rpc = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # keep test/demo output quiet

            def _json(self, obj, status=200):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                qs = parse_qs(parsed.query)
                try:
                    if path == "/status":
                        self._json(rpc._status())
                    elif path == "/chain":
                        limit = int(qs.get("limit", ["50"])[0])
                        self._json(rpc._chain_summary(limit))
                    elif path == "/block":
                        h = qs["hash"][0]
                        self._json(rpc._block_detail(h))
                    elif path == "/mempool":
                        self._json(rpc._mempool_summary())
                    elif path == "/balance":
                        addr = qs["address"][0]
                        self._json({"address": addr, "balance": rpc._balance(addr)})
                    elif path == "/utxos":
                        addr = qs["address"][0]
                        self._json({"address": addr, "utxos": rpc._utxos(addr)})
                    elif path == "/peers":
                        self._json(rpc._peers())
                    elif path == "/log":
                        n = int(qs.get("n", ["100"])[0])
                        self._json({"log": rpc.node.log[-n:]})
                    elif path == "/events":
                        rpc._handle_sse(self)
                    else:
                        self._json({"error": "not found"}, 404)
                except KeyError as e:
                    self._json({"error": f"missing parameter {e}"}, 400)
                except Exception as e:
                    self._json({"error": str(e)}, 400)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                except json.JSONDecodeError:
                    self._json({"error": "invalid JSON body"}, 400)
                    return
                try:
                    if self.path == "/submit_tx":
                        self._json(rpc._submit_tx(payload))
                    elif self.path == "/submit_block":
                        self._json(rpc._submit_block(payload))
                    elif self.path == "/mine/start":
                        rpc.miner.start()
                        self._json({"mining": True})
                    elif self.path == "/mine/stop":
                        rpc.miner.stop()
                        self._json({"mining": False})
                    elif self.path == "/connect":
                        rpc.node.connect(payload["host"], int(payload["port"]))
                        self._json({"connected": True})
                    elif self.path == "/sever":
                        rpc.node.sever(payload["peer"])
                        self._json({"severed": payload["peer"]})
                    elif self.path == "/heal":
                        rpc.node.heal(payload["peer"])
                        self._json({"healed": payload["peer"]})
                    elif self.path == "/sync":
                        rpc.node.request_sync(payload["peer"])
                        self._json({"requested": payload["peer"]})
                    else:
                        self._json({"error": "not found"}, 404)
                except ValidationError as e:
                    self._json({"error": str(e)}, 400)
                except Exception as e:
                    self._json({"error": str(e)}, 400)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()

    # -- handlers -----------------------------------------------------------

    def _status(self) -> dict:
        return {
            "node": self.node.node_name,
            "height": self.chain.height,
            "tip": self.chain.tip_hash.hex(),
            "difficulty_bits": self.chain.meta[self.chain.tip_hash].header.bits,
            "mempool_size": len(self.mempool),
            "peers": list(self.node.peers.keys()),
            "mining": self.miner._running.is_set(),
            "hashrate": self.miner.stats.last_hashrate,
            "blocks_found": self.miner.stats.blocks_found,
            "tips": [
                {"hash": h.hex(), "height": ht, "work": w, "active": h == self.chain.tip_hash}
                for h, ht, w in self.chain.all_tips()
            ],
        }

    def _chain_summary(self, limit: int) -> dict:
        out = []
        for h in self.chain.active_chain[-limit:]:
            meta = self.chain.meta[h]
            blk = self.chain.blocks[h]
            out.append({
                "hash": h.hex(), "height": meta.height, "timestamp": meta.header.timestamp,
                "bits": meta.header.bits, "n_tx": len(blk.transactions),
                "prev": meta.prev_hash.hex(),
            })
        return {"height": self.chain.height, "blocks": out}

    def _block_detail(self, h_hex: str) -> dict:
        h = bytes.fromhex(h_hex)
        blk = self.chain.blocks.get(h)
        if blk is None:
            raise KeyError("unknown block hash")
        meta = self.chain.meta[h]
        return {
            "hash": h.hex(), "height": meta.height, "prev": meta.prev_hash.hex(),
            "merkle_root": blk.header.merkle_root.hex(), "timestamp": blk.header.timestamp,
            "bits": blk.header.bits, "nonce": blk.header.nonce,
            "transactions": [
                {
                    "txid": tx.txid().hex(),
                    "coinbase": tx.is_coinbase(),
                    "inputs": [{"prev_txid": i.prev_txid.hex(), "prev_index": i.prev_index} for i in tx.inputs],
                    "outputs": [{"value": o.value, "script": repr(o.script_pubkey)} for o in tx.outputs],
                }
                for tx in blk.transactions
            ],
        }

    def _mempool_summary(self) -> dict:
        return {
            "size": len(self.mempool),
            "txs": [
                {"txid": txid.hex(), "fee": entry.fee, "n_in": len(entry.tx.inputs), "n_out": len(entry.tx.outputs)}
                for txid, entry in self.mempool.entries.items()
            ],
        }

    def _balance(self, addr: str) -> int:
        pkh = pubkey_hash_from_address(addr)
        return self.chain.balance_of(pkh)

    def _utxos(self, addr: str) -> list:
        pkh = pubkey_hash_from_address(addr)
        return [{"txid": txid.hex(), "index": idx, "value": txout.value}
                for (txid, idx), txout in self.chain.utxos_for(pkh)]

    def _peers(self) -> dict:
        return {"peers": list(self.node.peers.keys()), "severed": list(self.node.severed)}

    def _submit_tx(self, payload: dict) -> dict:
        tx = Transaction.deserialize(bytes.fromhex(payload["tx"]))
        ok = self.node.submit_tx(tx)
        if ok:
            self.miner.notify_new_work()
            self.publish_tx_event(tx)
        return {"accepted": ok, "txid": tx.txid().hex()}

    def _submit_block(self, payload: dict) -> dict:
        blk = Block.deserialize(bytes.fromhex(payload["block"]))
        ok = self.node.submit_block(blk)
        return {"accepted": ok, "hash": blk.hash().hex()}

    def _handle_sse(self, handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        q: queue.Queue = queue.Queue()
        with self._sub_lock:
            self._event_subscribers.append(q)
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    handler.wfile.write(b": keep-alive\n\n")
                    handler.wfile.flush()
                    continue
                data = f"data: {json.dumps(event)}\n\n".encode("utf-8")
                handler.wfile.write(data)
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self._sub_lock:
                if q in self._event_subscribers:
                    self._event_subscribers.remove(q)
