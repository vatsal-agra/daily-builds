"""Builds a single self-contained interactive HTML report from a recorded
simulator session. No server, no external JS/CSS, no CDN — everything is
inlined, same "server-free single-file viewer" pattern this repo has used
for its physics playgrounds and evolution replays. All data embedded is
literally what the engine produced (trade tape, candles, depth
snapshots, P&L history) — the page renders it, it never invents any of
it.
"""
import json


def build_report(session, out_path, title="Matchbook — Session Replay"):
    payload = json.dumps(session, separators=(",", ":"))
    # A `</` inside the JSON (e.g. a maliciously- or carelessly-named
    # agent from the pluggable Agent SDK) would otherwise prematurely
    # close this <script> block and inject arbitrary markup into the
    # report. Escaping it is inert to JSON.parse but neutralizes the break-out.
    payload = payload.replace("</", "<\\/")
    html = _HTML_TEMPLATE.replace("__TITLE__", title).replace("__DATA__", payload)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0b0e14; --panel: #12161f; --panel2: #171c27; --border: #232a38;
    --text: #e6e9ef; --muted: #8792a6; --green: #24c38a; --red: #f0556b;
    --accent: #4c8dff; --accent2: #f5b942;
  }
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; background: var(--bg); color: var(--text);
    font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
  header { padding: 16px 20px; border-bottom: 1px solid var(--border);
    display:flex; align-items:baseline; gap: 14px; flex-wrap: wrap; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; letter-spacing: .2px; }
  header .sub { color: var(--muted); font-size: 12.5px; }
  .layout { display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px; padding: 14px; }
  @media (max-width: 980px) { .layout { grid-template-columns: 1fr; } }
  .col { display:flex; flex-direction:column; gap:14px; min-width:0; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px; min-width:0; }
  .panel h2 { font-size: 12.5px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted);
    margin: 0 0 10px 0; font-weight: 600; }
  canvas { display:block; width:100%; }
  .controls { display:flex; align-items:center; gap:10px; padding: 10px 20px; border-bottom: 1px solid var(--border);
    background: var(--panel2); position: sticky; top:0; z-index: 5; flex-wrap: wrap; }
  button { background: var(--accent); color: #06101f; border: none; border-radius: 6px; padding: 7px 12px;
    font-weight: 600; cursor: pointer; font-size: 13px; }
  button.secondary { background: var(--panel); color: var(--text); border: 1px solid var(--border); }
  button:active { transform: translateY(1px); }
  input[type=range] { flex: 1; min-width: 120px; accent-color: var(--accent); }
  .tick-label { font-variant-numeric: tabular-nums; color: var(--muted); min-width: 130px; text-align:right; }
  select { background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--border); white-space:nowrap; }
  th:first-child, td:first-child { text-align: left; }
  .pos { color: var(--green); } .neg { color: var(--red); }
  .depth-row { display:grid; grid-template-columns: 1fr 1fr; gap: 2px; font-variant-numeric: tabular-nums; }
  .bidbar, .askbar { position:relative; height: 18px; border-radius: 3px; overflow:hidden; background: var(--panel2); }
  .bidbar .fill { position:absolute; right:0; top:0; bottom:0; background: rgba(36,195,138,.30); }
  .askbar .fill { position:absolute; left:0; top:0; bottom:0; background: rgba(240,85,107,.30); }
  .depth-row span { position:relative; z-index:1; padding: 0 6px; font-size:12.5px; line-height:18px; }
  .tape-row { display:flex; justify-content:space-between; font-size: 12.5px; padding: 2px 0; border-bottom: 1px dashed var(--border); }
  .tape-scroll { max-height: 260px; overflow-y: auto; }
  .badge { display:inline-block; padding: 1px 7px; border-radius: 100px; font-size: 11px; font-weight:700; }
  .badge.buy { background: rgba(36,195,138,.18); color: var(--green); }
  .badge.sell { background: rgba(240,85,107,.18); color: var(--red); }
  footer { padding: 16px 20px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--border); }
  .stat { display:flex; flex-direction:column; gap:2px; }
  .stat .v { font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .stat .k { font-size: 11px; color: var(--muted); text-transform:uppercase; letter-spacing:.06em; }
  .stats-row { display:flex; gap: 22px; flex-wrap: wrap; }
</style>
</head>
<body>
<header>
  <h1>Matchbook</h1>
  <div class="sub">from-scratch limit order book + multi-agent market simulator — session replay</div>
</header>
<div class="controls">
  <button id="playBtn">▶ Play</button>
  <button class="secondary" id="stepBackBtn">◀ Step</button>
  <button class="secondary" id="stepFwdBtn">Step ▶</button>
  <input type="range" id="scrubber" min="0" value="0" step="1">
  <span class="tick-label" id="tickLabel">tick 0</span>
  <select id="speedSel">
    <option value="240">1×</option>
    <option value="80">3×</option>
    <option value="24">10×</option>
    <option value="6" selected>40×</option>
  </select>
  <select id="symbolSel"></select>
</div>
<div class="layout">
  <div class="col">
    <div class="panel">
      <h2>Price — candlesticks</h2>
      <canvas id="candleCanvas" height="260"></canvas>
    </div>
    <div class="panel">
      <h2>Cumulative P&amp;L by agent</h2>
      <canvas id="pnlCanvas" height="200"></canvas>
      <div id="pnlLegend" style="display:flex; flex-wrap:wrap; gap:10px 16px; margin-top:10px; font-size:12px; color:var(--muted);"></div>
    </div>
    <div class="panel">
      <h2>Trade tape</h2>
      <div class="tape-scroll" id="tape"></div>
    </div>
  </div>
  <div class="col">
    <div class="panel">
      <h2>Session</h2>
      <div class="stats-row" id="statsRow"></div>
    </div>
    <div class="panel">
      <h2>Order book depth</h2>
      <div id="depthLadder"></div>
    </div>
    <div class="panel">
      <h2>Leaderboard</h2>
      <table id="leaderboard"><thead><tr><th>Agent</th><th>P&amp;L (as of tick)</th><th>Final inventory</th></tr></thead><tbody></tbody></table>
    </div>
  </div>
</div>
<footer>Everything on this page is a real recording of one deterministic, seeded simulation run — no data was hand-authored. Scrub the timeline to replay the whole session.</footer>

<script>
const DATA = __DATA__;
const symbols = Object.keys(DATA.symbols);
let activeSymbol = symbols[0];

const symbolSel = document.getElementById('symbolSel');
symbols.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; symbolSel.appendChild(o); });
symbolSel.addEventListener('change', () => { activeSymbol = symbolSel.value; render(); });

const scrubber = document.getElementById('scrubber');
const tickLabel = document.getElementById('tickLabel');
const totalTicks = DATA.total_ticks;
scrubber.max = totalTicks;
scrubber.value = totalTicks;

let playing = false;
let playTimer = null;

document.getElementById('playBtn').addEventListener('click', () => {
  playing = !playing;
  document.getElementById('playBtn').textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing) {
    schedule();
  } else {
    // Pausing must stop immediately — a timer left pending would still
    // fire once and silently advance the scrubber past where the user
    // paused it.
    clearTimeout(playTimer);
  }
});
document.getElementById('stepFwdBtn').addEventListener('click', () => { step(1); });
document.getElementById('stepBackBtn').addEventListener('click', () => { step(-1); });
scrubber.addEventListener('input', () => { render(); });

function schedule() {
  if (!playing) return;
  const speed = parseInt(document.getElementById('speedSel').value, 10);
  playTimer = setTimeout(() => {
    if (!playing) return;  // pause may have fired while this timer was in flight
    step(Math.max(1, Math.round(totalTicks / 400)));
    if (playing) schedule();
  }, speed);
}
function step(delta) {
  let v = parseInt(scrubber.value, 10) + delta;
  v = Math.max(0, Math.min(totalTicks, v));
  scrubber.value = v;
  render();
  if (v >= totalTicks) { playing = false; document.getElementById('playBtn').textContent = '▶ Play'; clearTimeout(playTimer); }
}

function fmtPnl(v) {
  const s = (v/100).toFixed(2);
  return (v >= 0 ? '+$' : '-$') + Math.abs(v/100).toFixed(2);
}
function cls(v) { return v >= 0 ? 'pos' : 'neg'; }

function render() {
  const t = parseInt(scrubber.value, 10);
  tickLabel.textContent = 'tick ' + t + ' / ' + totalTicks;
  drawCandles(t);
  drawPnl(t);
  drawTape(t);
  drawDepth(t);
  drawLeaderboard(t);
  drawStats(t);
}

function drawStats(t) {
  const sym = DATA.symbols[activeSymbol];
  const trades = sym.trades.filter(tr => tr.ts <= t);
  const last = trades.length ? trades[trades.length-1].price : null;
  const el = document.getElementById('statsRow');
  el.innerHTML = '';
  const items = [
    ['Last price', last !== null ? '$'+(last/100).toFixed(2) : '—'],
    ['Trades so far', trades.length],
    ['Symbols', symbols.length],
    ['Agents', DATA.agents.length],
  ];
  items.forEach(([k,v]) => {
    const d = document.createElement('div'); d.className = 'stat';
    d.innerHTML = '<div class="v">'+v+'</div><div class="k">'+k+'</div>';
    el.appendChild(d);
  });
}

function drawCandles(t) {
  const canvas = document.getElementById('candleCanvas');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = 260;
  canvas.width = w*dpr; canvas.height = h*dpr;
  const ctx = canvas.getContext('2d'); ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,w,h);
  const candles = DATA.symbols[activeSymbol].candles.filter(c => c.t_start <= t);
  if (!candles.length) { ctx.fillStyle = '#8792a6'; ctx.fillText('no trades yet', 10, 20); return; }
  const shown = candles.slice(-80);
  let lo = Infinity, hi = -Infinity;
  shown.forEach(c => { lo = Math.min(lo, c.low); hi = Math.max(hi, c.high); });
  if (lo === hi) { lo -= 10; hi += 10; }
  const pad = (hi-lo)*0.08; lo -= pad; hi += pad;
  const y = p => h - ((p - lo) / (hi - lo)) * h;
  const cw = w / shown.length;
  shown.forEach((c, i) => {
    const x = i*cw + cw/2;
    const up = c.close >= c.open;
    ctx.strokeStyle = ctx.fillStyle = up ? '#24c38a' : '#f0556b';
    ctx.beginPath(); ctx.moveTo(x, y(c.high)); ctx.lineTo(x, y(c.low)); ctx.stroke();
    const bodyW = Math.max(2, cw*0.6);
    const yo = y(c.open), yc = y(c.close);
    ctx.fillRect(x - bodyW/2, Math.min(yo,yc), bodyW, Math.max(1, Math.abs(yc-yo)));
  });
}

// 12 visually distinct colors — enough that the shipped 10-agent demo
// never has two agents sharing a color (a 7-color palette meant 3 of
// the 10 lines silently doubled up on an earlier agent's color).
const PALETTE = ['#4c8dff','#f5b942','#24c38a','#f0556b','#b57bf2','#37c9d6',
                  '#ff8a5c','#e2e86b','#7ee787','#ff7ab6','#8ea1ff','#d9a066'];

function drawLegend() {
  const el = document.getElementById('pnlLegend');
  el.innerHTML = DATA.agents.map((a, i) =>
    '<span><span style="display:inline-block;width:9px;height:9px;border-radius:2px;'
    + 'background:' + PALETTE[i % PALETTE.length] + ';margin-right:5px;vertical-align:middle;"></span>' + a + '</span>'
  ).join('');
}

function drawPnl(t) {
  const canvas = document.getElementById('pnlCanvas');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = 200;
  canvas.width = w*dpr; canvas.height = h*dpr;
  const ctx = canvas.getContext('2d'); ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,w,h);
  const palette = PALETTE;
  let lo = 0, hi = 0;
  DATA.agents.forEach(a => {
    (DATA.pnl_history[a] || []).forEach(([tt,v]) => { if (tt<=t) { lo = Math.min(lo,v); hi = Math.max(hi,v); } });
  });
  if (lo === hi) { lo -= 100; hi += 100; }
  const pad = (hi-lo)*0.1; lo -= pad; hi += pad;
  const y = v => h - ((v - lo) / (hi - lo)) * h;
  ctx.strokeStyle = '#232a38'; ctx.beginPath(); ctx.moveTo(0, y(0)); ctx.lineTo(w, y(0)); ctx.stroke();
  DATA.agents.forEach((a, i) => {
    const series = (DATA.pnl_history[a] || []).filter(([tt]) => tt <= t);
    if (!series.length) return;
    ctx.strokeStyle = palette[i % palette.length];
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    series.forEach(([tt,v], j) => {
      const x = (tt / totalTicks) * w;
      if (j===0) ctx.moveTo(x, y(v)); else ctx.lineTo(x, y(v));
    });
    ctx.stroke();
  });
}

function drawTape(t) {
  const sym = DATA.symbols[activeSymbol];
  const trades = sym.trades.filter(tr => tr.ts <= t).slice(-60).reverse();
  const el = document.getElementById('tape');
  el.innerHTML = trades.map(tr => {
    const side = tr.aggressor_side === 'BUY' ? 'buy' : 'sell';
    return '<div class="tape-row"><span><span class="badge '+side+'">'+tr.aggressor_side+'</span> '
      + tr.taker_owner + ' ⇄ ' + tr.maker_owner + '</span>'
      + '<span>$'+(tr.price/100).toFixed(2)+' × '+tr.qty+' <span style="color:var(--muted)">t'+tr.ts+'</span></span></div>';
  }).join('') || '<div style="color:var(--muted)">no trades yet</div>';
}

function nearestSnapshot(snapshots, t) {
  let best = null;
  for (const s of snapshots) { if (s.t <= t) best = s; else break; }
  return best;
}

function drawDepth(t) {
  const sym = DATA.symbols[activeSymbol];
  const snap = nearestSnapshot(sym.depth_snapshots, t);
  const el = document.getElementById('depthLadder');
  if (!snap) { el.innerHTML = '<div style="color:var(--muted)">no book yet</div>'; return; }
  const maxQty = Math.max(1, ...snap.bids.map(r=>r[1]), ...snap.asks.map(r=>r[1]));
  const rows = Math.max(snap.bids.length, snap.asks.length);
  let html = '';
  for (let i=0;i<rows;i++) {
    const bid = snap.bids[i], ask = snap.asks[i];
    html += '<div class="depth-row">';
    html += bid ? '<div class="bidbar"><div class="fill" style="width:'+(bid[1]/maxQty*100)+'%"></div><span>'+bid[1]+' @ $'+(bid[0]/100).toFixed(2)+'</span></div>' : '<div></div>';
    html += ask ? '<div class="askbar"><div class="fill" style="width:'+(ask[1]/maxQty*100)+'%"></div><span>$'+(ask[0]/100).toFixed(2)+' @ '+ask[1]+'</span></div>' : '<div></div>';
    html += '</div>';
  }
  el.innerHTML = html;
}

function drawLeaderboard(t) {
  const tbody = document.querySelector('#leaderboard tbody');
  const rows = DATA.agents.map(a => {
    const series = (DATA.pnl_history[a] || []).filter(([tt]) => tt <= t);
    const pnl = series.length ? series[series.length-1][1] : 0;
    const inv = DATA.final_inventory[a] || {};
    const invStr = Object.entries(inv).map(([s,q]) => s+':'+q).join(' ') || '—';
    return [a, pnl, invStr];
  }).sort((a,b) => b[1]-a[1]);
  tbody.innerHTML = rows.map(([a,pnl,inv]) =>
    '<tr><td>'+a+'</td><td class="'+cls(pnl)+'">'+fmtPnl(pnl)+'</td><td>'+inv+'</td></tr>').join('');
}

drawLegend();
render();
window.addEventListener('resize', render);
</script>
</body>
</html>
"""
