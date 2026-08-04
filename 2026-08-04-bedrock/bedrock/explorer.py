"""A server-backed block explorer + wallet UI. All blockchain logic runs on
the server (bedrock.node.Node); the browser only renders JSON the server
computed and posts user actions back — the same zero-client-logic pattern
this repo's Gambit/Formulate/Faraday builds use.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from bedrock.chain import COIN, ChainError, block_subsidy
from bedrock.mempool import MempoolError
from bedrock.node import Node
from bedrock.wallet import Wallet, WalletError

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bedrock Explorer</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0b0f14; --panel: #121821; --panel-2: #182231; --border: #263041;
    --text: #e7edf5; --muted: #8ea1b8; --accent: #f7931a; --accent-2: #38bdf8;
    --good: #34d399; --bad: #f87171; --mono: "SF Mono", Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f4f6fa; --panel:#ffffff; --panel-2:#eef2f8; --border:#dbe3ee;
      --text:#0f172a; --muted:#5b6b82; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  header { display:flex; align-items:center; gap:12px; padding:16px 24px;
    border-bottom:1px solid var(--border); position:sticky; top:0; background:var(--bg); z-index:5; }
  header .logo { font-weight:800; font-size:20px; letter-spacing:.02em; }
  header .logo span { color:var(--accent); }
  .stat { font-family:var(--mono); font-size:13px; color:var(--muted); }
  .stat b { color:var(--text); }
  main { max-width:1080px; margin:0 auto; padding:20px 24px 60px; display:grid; gap:20px;
    grid-template-columns: 1fr 1fr; }
  @media (max-width:800px){ main{ grid-template-columns:1fr; } }
  .panel { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:18px; }
  .panel h2 { margin:0 0 12px; font-size:14px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
  .full { grid-column: 1 / -1; }
  button { background:var(--accent); color:#1a1206; border:none; border-radius:8px;
    padding:9px 14px; font-weight:700; cursor:pointer; font-size:13px; }
  button.secondary { background:var(--panel-2); color:var(--text); border:1px solid var(--border); }
  button:disabled { opacity:.5; cursor:not-allowed; }
  input, select { background:var(--panel-2); border:1px solid var(--border); color:var(--text);
    border-radius:8px; padding:8px 10px; font-family:var(--mono); font-size:13px; width:100%; }
  label { font-size:12px; color:var(--muted); display:block; margin:10px 0 4px; }
  .row { display:flex; gap:8px; align-items:end; flex-wrap:wrap; }
  .mono { font-family:var(--mono); }
  .hash { font-family:var(--mono); font-size:12px; color:var(--accent-2); word-break:break-all; cursor:pointer; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 4px; border-bottom:1px solid var(--border); }
  th { color:var(--muted); font-weight:600; font-size:11px; text-transform:uppercase; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; }
  .pill.good { background:rgba(52,211,153,.15); color:var(--good); }
  .pill.bad { background:rgba(248,113,113,.15); color:var(--bad); }
  .msg { font-size:12px; margin-top:8px; min-height:16px; }
  .msg.err { color:var(--bad); }
  .msg.ok { color:var(--good); }
  .empty { color:var(--muted); font-size:13px; padding:8px 0; }
  select.wallet-picker { margin-bottom:6px; }
  .wallet-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border); font-size:13px; }
  #blockDetail { white-space:pre-wrap; font-family:var(--mono); font-size:12px; max-height:320px; overflow:auto;
    background:var(--panel-2); border-radius:8px; padding:10px; margin-top:10px; display:none; }
</style>
</head>
<body>
<header>
  <div class="logo">BED<span>ROCK</span></div>
  <div class="stat">height <b id="statHeight">-</b></div>
  <div class="stat">tip <b id="statTip">-</b></div>
  <div class="stat">mempool <b id="statMempool">-</b></div>
  <div class="stat">peers <b id="statPeers">-</b></div>
</header>
<main>
  <div class="panel">
    <h2>Wallets</h2>
    <div id="walletList" class="empty">No wallets yet.</div>
    <button id="newWalletBtn">+ New wallet</button>
    <div id="walletMsg" class="msg"></div>
  </div>

  <div class="panel">
    <h2>Send</h2>
    <label>From</label>
    <select id="fromWallet" class="wallet-picker"></select>
    <label>To address</label>
    <input id="toAddress" placeholder="paste an address">
    <div class="row">
      <div style="flex:1"><label>Amount (shards)</label><input id="amount" type="number" min="1" value="100000000"></div>
      <div style="flex:1"><label>Fee (shards)</label><input id="fee" type="number" min="0" value="1000"></div>
    </div>
    <div class="row" style="margin-top:12px">
      <button id="sendBtn">Sign &amp; broadcast</button>
    </div>
    <div id="sendMsg" class="msg"></div>
  </div>

  <div class="panel">
    <h2>Miner</h2>
    <label>Reward address</label>
    <select id="minerWallet" class="wallet-picker"></select>
    <button id="mineBtn">Mine one block</button>
    <div id="mineMsg" class="msg"></div>
  </div>

  <div class="panel">
    <h2>Mempool</h2>
    <div id="mempoolList" class="empty">Empty.</div>
  </div>

  <div class="panel full">
    <h2>Chain</h2>
    <table>
      <thead><tr><th>Height</th><th>Hash</th><th>Txs</th><th>Reward</th><th>Time</th></tr></thead>
      <tbody id="blockTable"></tbody>
    </table>
    <div id="blockDetail"></div>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const COIN = 100000000;
const fmt = (v) => (v / COIN).toFixed(4);

async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}

let wallets = [];

function renderWalletPickers() {
  for (const id of ['fromWallet', 'minerWallet']) {
    const sel = $(id);
    const prev = sel.value;
    sel.innerHTML = wallets.map(w => `<option value="${w.address}">${w.address.slice(0,10)}... (${fmt(w.balance)})</option>`).join('');
    if (prev) sel.value = prev;
  }
}

async function refreshWallets() {
  const data = await api('/api/wallets');
  wallets = data.wallets;
  const list = $('walletList');
  list.innerHTML = wallets.length ? '' : '';
  list.classList.toggle('empty', wallets.length === 0);
  if (!wallets.length) { list.textContent = 'No wallets yet.'; }
  else {
    list.innerHTML = wallets.map(w =>
      `<div class="wallet-row"><span class="hash" title="${w.address}">${w.address.slice(0,14)}...</span><span class="mono">${fmt(w.balance)}</span></div>`
    ).join('');
  }
  renderWalletPickers();
}

async function refreshStatus() {
  const s = await api('/api/status');
  $('statHeight').textContent = s.height;
  $('statTip').textContent = s.tip_hash.slice(0, 12) + '...';
  $('statMempool').textContent = s.mempool_size;
  $('statPeers').textContent = s.peer_count;
}

async function refreshMempool() {
  const data = await api('/api/mempool');
  const el = $('mempoolList');
  if (!data.transactions.length) { el.className = 'empty'; el.textContent = 'Empty.'; return; }
  el.className = '';
  el.innerHTML = '<table><thead><tr><th>Txid</th><th>Outputs</th></tr></thead><tbody>' +
    data.transactions.map(t => `<tr><td class="hash">${t.txid.slice(0,16)}...</td><td class="mono">${t.outputs.length}</td></tr>`).join('') +
    '</tbody></table>';
}

async function refreshBlocks() {
  const data = await api('/api/blocks?limit=25');
  const tbody = $('blockTable');
  tbody.innerHTML = data.blocks.map(b => `
    <tr onclick="showBlock('${b.hash}')" style="cursor:pointer">
      <td>${b.height}</td>
      <td class="hash">${b.hash.slice(0,18)}...</td>
      <td>${b.tx_count}</td>
      <td class="mono">${fmt(b.reward)}</td>
      <td class="mono">${new Date(b.timestamp*1000).toLocaleTimeString()}</td>
    </tr>`).join('');
}

async function showBlock(hash) {
  const data = await api('/api/block/' + hash);
  const el = $('blockDetail');
  el.style.display = 'block';
  el.textContent = JSON.stringify(data, null, 2);
}

async function refreshAll() {
  await Promise.all([refreshStatus(), refreshWallets(), refreshMempool(), refreshBlocks()]);
}

$('newWalletBtn').onclick = async () => {
  try {
    const w = await api('/api/wallet/new', { method: 'POST' });
    $('walletMsg').className = 'msg ok';
    $('walletMsg').textContent = 'Created ' + w.address.slice(0,14) + '... (private key shown once: ' + w.private_key.slice(0,10) + '...)';
    await refreshWallets();
  } catch (e) { $('walletMsg').className = 'msg err'; $('walletMsg').textContent = e.message; }
};

$('sendBtn').onclick = async () => {
  const from_address = $('fromWallet').value;
  const to_address = $('toAddress').value.trim();
  const amount = parseInt($('amount').value, 10);
  const fee = parseInt($('fee').value, 10);
  try {
    const r = await api('/api/tx/send', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({from_address, to_address, amount, fee})
    });
    $('sendMsg').className = 'msg ok';
    $('sendMsg').textContent = 'Broadcast ' + r.txid.slice(0,16) + '...';
    await refreshAll();
  } catch (e) { $('sendMsg').className = 'msg err'; $('sendMsg').textContent = e.message; }
};

$('mineBtn').onclick = async () => {
  const miner_address = $('minerWallet').value;
  if (!miner_address) { $('mineMsg').className='msg err'; $('mineMsg').textContent='create a wallet first'; return; }
  $('mineBtn').disabled = true;
  $('mineMsg').textContent = 'mining...';
  try {
    const r = await api('/api/mine', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({miner_address})
    });
    $('mineMsg').className = 'msg ok';
    $('mineMsg').textContent = 'Mined block at height ' + r.height + ' (' + r.status + ')';
    await refreshAll();
  } catch (e) { $('mineMsg').className = 'msg err'; $('mineMsg').textContent = e.message; }
  finally { $('mineBtn').disabled = false; }
};

refreshAll();
setInterval(refreshAll, 3000);
</script>
</body>
</html>
"""


class ExplorerState:
    """Holds the live Node plus server-managed demo wallets (private keys
    live only in server memory, same tradeoff a hosted demo wallet always
    makes — documented in the README, not something to do with real funds)."""

    def __init__(self, node: Node, network=None):
        self.node = node
        self.network = network
        self.wallets = {}  # address -> Wallet
        # Share the NetworkNode's own lock when one is attached: node.chain
        # and node.mempool are the same mutable objects both this HTTP
        # server and the P2P gossip threads touch, so they must serialize
        # through one lock, not two independent ones that each believe they
        # have exclusive access (see NetworkNode.__init__'s docstring note).
        self.lock = network.lock if network is not None else threading.RLock()

    def new_wallet(self) -> Wallet:
        w = Wallet.generate()
        with self.lock:
            self.wallets[w.address] = w
        return w


def make_handler(state: ExplorerState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Bedrock/1.0"

        def log_message(self, fmt, *args):
            pass  # keep test/demo output quiet

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed JSON body: {exc}") from exc

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            try:
                if path == "/":
                    self._send_html(INDEX_HTML)
                elif path == "/api/status":
                    self._send_json(self._status())
                elif path == "/api/blocks":
                    limit = int(qs.get("limit", ["25"])[0])
                    self._send_json({"blocks": self._recent_blocks(limit)})
                elif path.startswith("/api/block/"):
                    block_hash = path[len("/api/block/"):]
                    self._send_json(self._block_detail(block_hash))
                elif path == "/api/mempool":
                    self._send_json(self._mempool())
                elif path == "/api/wallets":
                    self._send_json(self._wallets())
                elif path.startswith("/api/wallet/") and path.endswith("/balance"):
                    address = path[len("/api/wallet/"):-len("/balance")]
                    self._send_json({"address": address, "balance": state.node.balance(address)})
                else:
                    self._send_json({"error": "not found"}, status=404)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/wallet/new":
                    w = state.new_wallet()
                    self._send_json({"address": w.address, "private_key": w.to_wif(), "balance": 0})
                elif path == "/api/tx/send":
                    self._send_json(self._send_tx(self._read_json_body()))
                elif path == "/api/mine":
                    self._send_json(self._mine(self._read_json_body()))
                else:
                    self._send_json({"error": "not found"}, status=404)
            except (ChainError, MempoolError, WalletError, ValueError, KeyError) as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"error": f"internal error: {exc}"}, status=500)

        # -- handlers ---------------------------------------------------------

        def _status(self) -> dict:
            with state.lock:
                return {
                    "height": state.node.chain.height,
                    "tip_hash": state.node.chain.tip_hash,
                    "mempool_size": len(state.node.mempool),
                    "peer_count": state.network.peer_count() if state.network else 0,
                }

        def _recent_blocks(self, limit: int) -> list:
            with state.lock:
                chain = state.node.chain
                out = []
                height = chain.height
                while height >= 0 and len(out) < limit:
                    block = chain.block_at_height(height)
                    out.append({
                        "height": height,
                        "hash": block.hash,
                        "tx_count": len(block.transactions),
                        "reward": block.transactions[0].total_output_value(),
                        "timestamp": block.header.timestamp,
                    })
                    height -= 1
                return out

        def _block_detail(self, block_hash: str) -> dict:
            with state.lock:
                block = state.node.chain.get_block(block_hash)
                if block is None:
                    raise ValueError("no such block")
                entry = state.node.chain.get_entry(block_hash)
                return {
                    "hash": block.hash,
                    "height": entry.height,
                    "prev_hash": block.header.prev_hash,
                    "merkle_root": block.header.merkle_root,
                    "timestamp": block.header.timestamp,
                    "target": hex(block.header.target),
                    "nonce": block.header.nonce,
                    "cumulative_work": entry.cumulative_work,
                    "transactions": [
                        {
                            "txid": tx.txid,
                            "is_coinbase": tx.is_coinbase,
                            "inputs": len(tx.inputs),
                            "outputs": [{"value": o.value, "address": o.address} for o in tx.outputs],
                        }
                        for tx in block.transactions
                    ],
                }

        def _mempool(self) -> dict:
            with state.lock:
                return {
                    "transactions": [
                        {
                            "txid": tx.txid,
                            "outputs": [{"value": o.value, "address": o.address} for o in tx.outputs],
                        }
                        for tx in state.node.mempool.select_for_block(state.node.chain)
                    ]
                }

        def _wallets(self) -> dict:
            with state.lock:
                return {
                    "wallets": [
                        {"address": addr, "balance": state.node.balance(addr)}
                        for addr in state.wallets
                    ]
                }

        def _send_tx(self, body: dict) -> dict:
            from_address = body.get("from_address")
            to_address = body.get("to_address")
            amount = body.get("amount")
            fee = body.get("fee", 0)
            if not from_address or from_address not in state.wallets:
                raise ValueError("unknown from_address (create/select a wallet first)")
            if not isinstance(amount, int) or amount <= 0:
                raise ValueError("amount must be a positive integer number of shards")
            if not isinstance(fee, int) or fee < 0:
                raise ValueError("fee must be a non-negative integer")
            with state.lock:
                wallet = state.wallets[from_address]
                tx = wallet.send(state.node.chain, state.node.mempool, to_address, amount, fee=fee)
                if state.network:
                    state.network.announce_tx(tx)
            return {"txid": tx.txid}

        def _mine(self, body: dict) -> dict:
            miner_address = body.get("miner_address")
            if not miner_address:
                raise ValueError("miner_address is required")
            with state.lock:
                block, status = state.node.mine_block(miner_address, max_nonce=50_000_000)
                if state.network:
                    state.network.announce_block(block)
            return {"hash": block.hash, "height": state.node.chain.height, "status": status}

    return Handler


def serve(node: Node = None, network=None, host: str = "127.0.0.1", port: int = 8420) -> ThreadingHTTPServer:
    state = ExplorerState(node or Node(), network=network)
    handler = make_handler(state)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.bedrock_state = state
    return httpd
