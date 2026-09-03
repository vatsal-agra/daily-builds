"""A stdlib-http.server-backed block explorer: every page is rendered
server-side from a live FullNode's actual chain/mempool state — the browser
holds no ledger logic of its own, same pattern as this repo's
Gambit/Formulate/Unify visualizers."""
from __future__ import annotations

import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PAGE_STYLE = """
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 980px;
         margin: 2rem auto; padding: 0 1.25rem; background:#0b0e14; color:#e6e6e6; }
  a { color: #6cb6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; color:#9fb3c8; }
  table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; }
  th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #263042; font-size: 0.92rem; }
  th { color: #7d93ad; font-weight: 600; }
  .mono { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.85rem; word-break: break-all; }
  .badge { display:inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75rem; }
  .badge.coinbase { background:#2c4a2c; color:#9fe89f; }
  .badge.tip { background:#2c3a4a; color:#9fc8ff; }
  .card { background:#121722; border:1px solid #263042; border-radius: 10px; padding: 1rem 1.25rem; margin-bottom:1rem; }
  .stat { display:inline-block; margin-right: 2rem; }
  .stat b { display:block; font-size:1.3rem; color:#e6e6e6; }
  .stat span { color:#7d93ad; font-size:0.8rem; }
  nav { margin-bottom: 1.5rem; }
</style>
"""


def _e(s) -> str:
    return html.escape(str(s))


class ExplorerHandler(BaseHTTPRequestHandler):
    node = None  # set by make_server

    def log_message(self, fmt, *args):
        pass  # keep test/demo output quiet

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/favicon.ico":
                # Browsers request this automatically; without an explicit
                # response it 404s and shows up as a spurious console error
                # in a headless-browser check. A 204 is enough to silence it.
                self.send_response(204)
                self.end_headers()
                return
            if path == "/" or path == "":
                body = self._render_index()
            elif path == "/block":
                body = self._render_block(qs.get("hash", [""])[0])
            elif path == "/address":
                body = self._render_address(qs.get("addr", [""])[0])
            elif path == "/mempool":
                body = self._render_mempool()
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"not found")
                return
        except Exception as e:  # noqa: BLE001 - explorer must never crash the server thread
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"internal error: {e}".encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    # ------------------------------------------------------------------
    def _nav(self) -> str:
        return '<nav><a href="/">chain</a> · <a href="/mempool">mempool</a></nav>'

    def _render_index(self) -> str:
        chain = self.node.chain
        rows = []
        tip_badge = ' <span class="badge tip">tip</span>'
        for block in reversed(chain.active_chain()[-30:]):
            is_tip = block.hash() == chain.tip_hash
            rows.append(
                f"<tr><td>{block.height}</td>"
                f"<td class='mono'><a href='/block?hash={block.hash()}'>{block.hash()[:18]}…</a>"
                f"{tip_badge if is_tip else ''}</td>"
                f"<td>{len(block.transactions)}</td>"
                f"<td>{block.header.bits:#010x}</td>"
                f"<td>{_e(f'{block.header.timestamp:.2f}')}</td></tr>"
            )
        total_supply = sum(t.amount for t, _h, _c in chain.utxo_set.utxos.values())
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>Keystone Explorer</title>{PAGE_STYLE}</head>
<body>{self._nav()}
<h1>Keystone — {_e(self.node.net.name)}</h1>
<div class="card">
  <div class="stat"><b>{chain.height()}</b><span>height</span></div>
  <div class="stat"><b>{len(chain.blocks)}</b><span>known blocks (incl. side branches)</span></div>
  <div class="stat"><b>{len(self.node.mempool)}</b><span>mempool</span></div>
  <div class="stat"><b>{self.node.net.peer_count()}</b><span>peers</span></div>
  <div class="stat"><b>{self.node.net.reorg_count}</b><span>reorgs</span></div>
  <div class="stat"><b>{total_supply}</b><span>circulating supply</span></div>
</div>
<h2>Recent blocks</h2>
<table><tr><th>height</th><th>hash</th><th>txs</th><th>bits</th><th>timestamp</th></tr>
{''.join(rows)}
</table>
</body></html>"""

    def _render_block(self, block_hash: str) -> str:
        block = self.node.chain.get_block(block_hash)
        if block is None:
            return f"<!doctype html><body>{self._nav()}<p>Unknown block {_e(block_hash)}</p></body>"
        tx_rows = []
        for tx in block.transactions:
            outs = "<br>".join(f"{o.amount} → {' '.join(o.script_pubkey)[:40]}…" for o in tx.outputs)
            kind = '<span class="badge coinbase">coinbase</span>' if tx.is_coinbase else ""
            tx_rows.append(f"<tr><td class='mono'>{tx.txid()[:18]}… {kind}</td><td>{outs}</td></tr>")
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>Block {block_hash[:10]}</title>{PAGE_STYLE}</head>
<body>{self._nav()}
<h1>Block #{block.height}</h1>
<div class="card mono">
  hash: {block_hash}<br>
  prev: <a href="/block?hash={block.header.prev_hash}">{block.header.prev_hash}</a><br>
  merkle_root: {block.header.merkle_root}<br>
  bits: {block.header.bits:#010x} &nbsp; nonce: {block.header.nonce}
</div>
<h2>Transactions ({len(block.transactions)})</h2>
<table><tr><th>txid</th><th>outputs</th></tr>{''.join(tx_rows)}</table>
</body></html>"""

    def _render_address(self, addr: str) -> str:
        from .wallet import Wallet
        try:
            pkh = Wallet.address_to_pubkey_hash(addr)
        except ValueError as e:
            return f"<!doctype html><body>{self._nav()}<p>Bad address: {_e(e)}</p></body>"
        balance = self.node.chain.utxo_set.balance_of(pkh)
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>Address</title>{PAGE_STYLE}</head>
<body>{self._nav()}<h1>Address</h1>
<div class="card mono">{_e(addr)}</div>
<div class="card"><div class="stat"><b>{balance}</b><span>balance</span></div></div>
</body></html>"""

    def _render_mempool(self) -> str:
        rows = []
        for tx in self.node.mempool.select_for_block():
            rows.append(
                f"<tr><td class='mono'>{tx.txid()[:18]}…</td><td>{len(tx.inputs)}</td>"
                f"<td>{len(tx.outputs)}</td><td>{self.node.mempool.fees[tx.txid()]}</td></tr>"
            )
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>Mempool</title>{PAGE_STYLE}</head>
<body>{self._nav()}<h1>Mempool ({len(self.node.mempool)})</h1>
<table><tr><th>txid</th><th>inputs</th><th>outputs</th><th>fee</th></tr>{''.join(rows)}</table>
</body></html>"""


def make_server(node, host: str = "127.0.0.1", port: int = 0):
    handler_cls = type("BoundExplorerHandler", (ExplorerHandler,), {"node": node})
    server = ThreadingHTTPServer((host, port), handler_cls)
    return server


def run_explorer_in_thread(node, host: str = "127.0.0.1", port: int = 0):
    server = make_server(node, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="explorer")
    thread.start()
    return server, thread
