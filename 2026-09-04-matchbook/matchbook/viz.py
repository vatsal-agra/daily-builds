"""Render one finished session (journal + trade tape + per-tick depth
history) into a single self-contained, no-server-required interactive HTML
file: a scrubbable OHLCV candlestick chart, a live order-book depth ladder,
and a scrolling trade tape, all driven off the same tick index by a
scrubber/play control.

No client-side matching logic of any kind -- everything the page shows was
computed by the real Python engine and is simply replayed here.
"""
from __future__ import annotations

import json

from .candles import build_candles
from .order import Trade


def _json_for_script(obj) -> str:
    """json.dumps, hardened against a `</script>` breakout if any embedded
    string (an agent id, a symbol) ever contained one."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def render_session_html(
    symbols: list[str],
    history: list[dict],
    trades: list[Trade],
    summary: dict,
    bar_size: int = 10,
    title: str = "Matchbook session replay",
) -> str:
    candles_by_symbol = {
        s: [c.to_dict() for c in build_candles(trades, s, bar_size=bar_size)] for s in symbols
    }
    trades_by_symbol = {
        s: [t.to_dict() for t in trades if t.symbol == s] for s in symbols
    }

    data = {
        "symbols": symbols,
        "history": history,
        "candles": candles_by_symbol,
        "trades": trades_by_symbol,
        "summary": summary,
        "barSize": bar_size,
    }

    return _TEMPLATE.replace("__TITLE__", title).replace("__DATA__", _json_for_script(data))


_TEMPLATE = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0b0f14; --panel: #121822; --panel-2: #0f141c; --border: #202a38;
    --text: #dfe6ee; --muted: #7d8ba0; --accent: #4fc3f7; --green: #35d68f;
    --red: #f0556d; --amber: #ffb454;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }
  header {
    padding: 16px 20px; border-bottom: 1px solid var(--border);
    display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  }
  header h1 { font-size: 17px; margin: 0; font-weight: 600; letter-spacing: 0.2px; }
  header .sub { color: var(--muted); font-size: 12.5px; }
  select {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 5px 8px; font-size: 13px;
  }
  main { display: grid; grid-template-columns: 1fr 300px; gap: 16px; padding: 16px 20px; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px; margin-bottom: 16px;
  }
  .panel h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px;
    color: var(--muted); margin: 0 0 10px 0; font-weight: 600;
  }
  canvas { display: block; width: 100%; }
  .controls { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
  .controls input[type=range] { flex: 1; accent-color: var(--accent); }
  button {
    background: var(--panel-2); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 13px;
  }
  button:hover { border-color: var(--accent); }
  .tickLabel { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 90px; text-align: right; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  td, th { padding: 2px 6px; text-align: right; font-size: 12.5px; }
  th { color: var(--muted); font-weight: 500; text-align: right; }
  .side-label { text-align: left; color: var(--muted); }
  .bid { color: var(--green); }
  .ask { color: var(--red); }
  .depth-bar-bid { background: rgba(53, 214, 143, 0.18); }
  .depth-bar-ask { background: rgba(240, 85, 109, 0.18); }
  #tape { max-height: 340px; overflow-y: auto; }
  #tape div { display: flex; justify-content: space-between; padding: 3px 2px; border-bottom: 1px solid var(--border); font-size: 12.5px; }
  #tape .buy { color: var(--green); }
  #tape .sell { color: var(--red); }
  .stat { display: flex; justify-content: space-between; padding: 3px 0; font-size: 12.5px; }
  .stat .k { color: var(--muted); }
  .agentRow.pos { color: var(--green); }
  .agentRow.neg { color: var(--red); }
</style>
</head>
<body>
<header>
  <h1>Matchbook &mdash; session replay</h1>
  <span class="sub">order-book depth · trade tape · OHLCV candles, all reconstructed from the real engine's journal</span>
  <select id="symbolSelect"></select>
</header>
<main>
  <div>
    <div class="panel">
      <h2>Price (OHLCV candles)</h2>
      <canvas id="candleCanvas" height="260"></canvas>
    </div>
    <div class="panel">
      <h2>Session replay</h2>
      <div class="controls">
        <button id="playBtn">&#9654; Play</button>
        <input type="range" id="scrubber" min="0" value="0" step="1">
        <span class="tickLabel" id="tickLabel">tick 0</span>
      </div>
    </div>
    <div class="panel">
      <h2>Order book depth</h2>
      <table>
        <thead><tr><th class="side-label">Bids</th><th></th><th></th><th class="side-label">Asks</th><th></th></tr>
        <tr><th class="side-label">Qty</th><th>Price</th><th>&nbsp;</th><th>Price</th><th>Qty</th></tr></thead>
        <tbody id="depthBody"></tbody>
      </table>
    </div>
  </div>
  <div>
    <div class="panel">
      <h2>Session summary</h2>
      <div id="summaryBody"></div>
    </div>
    <div class="panel">
      <h2>Trade tape</h2>
      <div id="tape"></div>
    </div>
  </div>
</main>
<script>
const DATA = __DATA__;
let symbol = DATA.symbols[0];
let tick = 0;
let playing = false;
let timer = null;

const symbolSelect = document.getElementById('symbolSelect');
DATA.symbols.forEach(s => {
  const opt = document.createElement('option');
  opt.value = s; opt.textContent = s;
  symbolSelect.appendChild(opt);
});
symbolSelect.value = symbol;
symbolSelect.addEventListener('change', () => { symbol = symbolSelect.value; render(); });

const scrubber = document.getElementById('scrubber');
scrubber.max = String(DATA.history.length - 1);
scrubber.addEventListener('input', () => { tick = parseInt(scrubber.value, 10); render(); });

document.getElementById('playBtn').addEventListener('click', () => {
  playing = !playing;
  document.getElementById('playBtn').innerHTML = playing ? '&#10074;&#10074; Pause' : '&#9654; Play';
  if (playing) {
    timer = setInterval(() => {
      tick = Math.min(tick + 1, DATA.history.length - 1);
      scrubber.value = String(tick);
      render();
      if (tick >= DATA.history.length - 1) { togglePause(); }
    }, 60);
  } else {
    clearInterval(timer);
  }
});
function togglePause() {
  playing = false;
  document.getElementById('playBtn').innerHTML = '&#9654; Play';
  clearInterval(timer);
}

function fmt(n, d) { return Number(n).toFixed(d === undefined ? 2 : d); }

function renderDepth() {
  const frame = DATA.history[tick];
  const book = frame.depths[symbol] || { bids: [], asks: [] };
  const rows = Math.max(book.bids.length, book.asks.length, 1);
  const maxQty = Math.max(1, ...book.bids.map(b => b[1]), ...book.asks.map(a => a[1]));
  let html = '';
  for (let i = 0; i < rows; i++) {
    const bid = book.bids[i], ask = book.asks[i];
    const bidPct = bid ? Math.round(100 * bid[1] / maxQty) : 0;
    const askPct = ask ? Math.round(100 * ask[1] / maxQty) : 0;
    html += `<tr>
      <td class="bid depth-bar-bid" style="background-size:${bidPct}% 100%;background-repeat:no-repeat;background-position:right">${bid ? bid[1] : ''}</td>
      <td class="bid">${bid ? fmt(bid[0]) : ''}</td>
      <td>&nbsp;</td>
      <td class="ask">${ask ? fmt(ask[0]) : ''}</td>
      <td class="ask depth-bar-ask" style="background-size:${askPct}% 100%;background-repeat:no-repeat">${ask ? ask[1] : ''}</td>
    </tr>`;
  }
  document.getElementById('depthBody').innerHTML = html;
}

function renderTape() {
  const frame = DATA.history[tick];
  const upTo = frame.seq;
  const list = (DATA.trades[symbol] || []).filter(t => t.seq < upTo).slice(-60).reverse();
  document.getElementById('tape').innerHTML = list.map(t =>
    `<div class="${t.aggressor_side === 'BUY' ? 'buy' : 'sell'}">
       <span>${t.aggressor_side} ${t.qty} @ ${fmt(t.price)}</span>
       <span>${t.buy_agent} / ${t.sell_agent}</span>
     </div>`
  ).join('') || '<div style="color:var(--muted)">no trades yet</div>';
}

function renderSummary() {
  const s = DATA.summary;
  let html = `
    <div class="stat"><span class="k">Total trades</span><span>${s.trade_count}</span></div>
    <div class="stat"><span class="k">Rejections</span><span>${s.rejections}</span></div>
    <div class="stat"><span class="k">Self-trade cancels</span><span>${s.stp_cancels}</span></div>`;
  for (const sym of DATA.symbols) {
    html += `<div class="stat"><span class="k">Last price (${sym})</span><span>${s.last_price[sym] !== undefined ? fmt(s.last_price[sym]) : '—'}</span></div>`;
  }
  html += '<h2 style="margin-top:14px">Agent P&amp;L (mark-to-market)</h2>';
  const agents = Object.keys(s.agents).sort((a, b) => s.agents[b].pnl - s.agents[a].pnl);
  html += agents.map(a => {
    const pnl = s.agents[a].pnl;
    return `<div class="stat agentRow ${pnl >= 0 ? 'pos' : 'neg'}"><span class="k">${a}</span><span>${fmt(pnl)}</span></div>`;
  }).join('');
  document.getElementById('summaryBody').innerHTML = html;
}

function renderCandles() {
  const canvas = document.getElementById('candleCanvas');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 600, h = 260;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const frame = DATA.history[tick];
  const allCandles = (DATA.candles[symbol] || []).filter(c => c.bucket * DATA.barSize < frame.seq);
  if (allCandles.length === 0) {
    ctx.fillStyle = '#7d8ba0'; ctx.fillText('no trades yet', 10, 20); return;
  }
  const pad = 30;
  const lo = Math.min(...allCandles.map(c => c.low));
  const hi = Math.max(...allCandles.map(c => c.high));
  const range = Math.max(0.01, hi - lo);
  const cw = Math.max(2, (w - pad * 2) / allCandles.length - 2);

  const y = (p) => pad + (1 - (p - lo) / range) * (h - pad * 2);

  ctx.strokeStyle = '#202a38'; ctx.fillStyle = '#7d8ba0'; ctx.font = '11px sans-serif';
  for (let i = 0; i <= 4; i++) {
    const price = lo + (range * i / 4);
    const yy = y(price);
    ctx.beginPath(); ctx.moveTo(pad, yy); ctx.lineTo(w - 5, yy); ctx.stroke();
    ctx.fillText(price.toFixed(2), 2, yy - 2);
  }

  allCandles.forEach((c, i) => {
    const x = pad + i * ((w - pad * 2) / allCandles.length);
    const up = c.close >= c.open;
    ctx.strokeStyle = ctx.fillStyle = up ? '#35d68f' : '#f0556d';
    ctx.beginPath(); ctx.moveTo(x + cw / 2, y(c.high)); ctx.lineTo(x + cw / 2, y(c.low)); ctx.stroke();
    const top = y(Math.max(c.open, c.close)), bot = y(Math.min(c.open, c.close));
    ctx.fillRect(x, top, cw, Math.max(1, bot - top));
  });
}

function render() {
  document.getElementById('tickLabel').textContent = `tick ${DATA.history[tick].tick}`;
  renderDepth();
  renderTape();
  renderSummary();
  renderCandles();
}
window.addEventListener('resize', renderCandles);
render();
</script>
</body>
</html>
"""
