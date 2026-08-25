"""Renders a self-contained, interactive HTML visualizer from a real
captured swarm event log (see node.EventLog / `skein swarm`'s
events.json). Every data point plotted comes from an actual recorded
event — connect/disconnect times, real block/piece transfers, real
choke/unchoke transitions — never synthesized.
"""

from __future__ import annotations

import json


def render_visualizer_html(data: dict) -> str:
    torrent = data.get("torrent", {})
    peers = data.get("peers", {})
    payload = json.dumps({"torrent": torrent, "peers": peers})

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Skein swarm replay — {torrent.get('name', 'torrent')}</title>
<style>
  :root {{
    --bg: #0b0f14; --panel: #121820; --ink: #e6edf3; --muted: #8b98a5;
    --accent: #4f9cff; --have: #33c17a; --missing: #263241; --grid-line: #1d2733;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--ink); font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 24px; line-height: 1.4;
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--grid-line); border-radius: 10px;
    padding: 16px; margin-bottom: 18px;
  }}
  .panel h2 {{ font-size: 14px; margin: 0 0 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
  .row {{ display: flex; align-items: center; gap: 10px; margin: 6px 0; }}
  .peer-label {{ width: 90px; font-size: 12px; color: var(--muted); flex-shrink: 0; }}
  .cells {{ display: flex; gap: 2px; flex-wrap: wrap; }}
  .cell {{
    width: 10px; height: 10px; border-radius: 2px; background: var(--missing);
    transition: background 120ms;
  }}
  .cell.have {{ background: var(--have); }}
  .cell.inflight {{ background: var(--accent); }}
  #scrubber {{ width: 100%; }}
  .controls {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
  #tlabel {{ font-variant-numeric: tabular-nums; color: var(--muted); font-size: 13px; width: 70px; }}
  button {{
    background: #1a2330; color: var(--ink); border: 1px solid var(--grid-line);
    border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 13px;
  }}
  button:hover {{ background: #212d3d; }}
  svg#ratechart {{ width: 100%; height: 160px; }}
  .choke-badge {{ font-size: 11px; padding: 1px 6px; border-radius: 10px; margin-left: 6px; }}
  .choke-badge.unchoked {{ background: #16382a; color: var(--have); }}
  .choke-badge.choked {{ background: #3a1f1f; color: #ff8f8f; }}
  .legend {{ font-size: 12px; color: var(--muted); display: flex; gap: 16px; margin-top: 8px; }}
  .swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
</style>
</head>
<body>
<h1>Skein swarm replay</h1>
<div class="meta" id="metaline"></div>

<div class="panel">
  <h2>Playback</h2>
  <div class="controls">
    <button id="playbtn">▶ Play</button>
    <span id="tlabel">t=0.0s</span>
    <input type="range" id="scrubber" min="0" max="1000" value="0">
  </div>
</div>

<div class="panel">
  <h2>Piece availability per peer (green = have, blue = requested)</h2>
  <div id="grid"></div>
  <div class="legend">
    <span><span class="swatch" style="background:var(--have)"></span>have</span>
    <span><span class="swatch" style="background:var(--accent)"></span>requested</span>
    <span><span class="swatch" style="background:var(--missing)"></span>missing</span>
  </div>
</div>

<div class="panel">
  <h2>Cumulative bytes downloaded per peer</h2>
  <svg id="ratechart" viewBox="0 0 600 160" preserveAspectRatio="none"></svg>
</div>

<div class="panel">
  <h2>Event log up to current time</h2>
  <div id="eventlist" style="max-height:220px; overflow:auto; font-family: ui-monospace, monospace; font-size:12px; color: var(--muted);"></div>
</div>

<script>
const DATA = {payload};
const torrent = DATA.torrent;
const peerNames = Object.keys(DATA.peers);
document.getElementById('metaline').textContent =
  `${{torrent.name}} — ${{torrent.num_pieces}} pieces x ${{torrent.piece_length}}B — info_hash ${{(torrent.info_hash||'').slice(0,16)}}… — peers: ${{peerNames.join(', ')}}`;

// Flatten + sort all events by time, tagged with which peer's log they came from.
let allEvents = [];
for (const name of peerNames) {{
  for (const ev of DATA.peers[name]) {{
    allEvents.push(Object.assign({{owner: name}}, ev));
  }}
}}
allEvents.sort((a, b) => a.t - b.t);
const maxT = allEvents.length ? allEvents[allEvents.length - 1].t : 1;

// Build the per-peer piece grid DOM once; cell state is recomputed on scrub.
const gridEl = document.getElementById('grid');
const cellsByPeer = {{}};
for (const name of peerNames) {{
  const row = document.createElement('div');
  row.className = 'row';
  const label = document.createElement('div');
  label.className = 'peer-label';
  label.textContent = name;
  const cells = document.createElement('div');
  cells.className = 'cells';
  const cellNodes = [];
  for (let i = 0; i < torrent.num_pieces; i++) {{
    const c = document.createElement('div');
    c.className = 'cell';
    cells.appendChild(c);
    cellNodes.push(c);
  }}
  cellsByPeer[name] = cellNodes;
  row.appendChild(label);
  row.appendChild(cells);
  gridEl.appendChild(row);
}}

function computeStateAt(t) {{
  // have[peer] = Set(piece indices verified complete by time t)
  // inflight[peer] = Set(piece indices with a block requested but not yet complete by time t)
  const have = {{}}, inflight = {{}}, downloaded = {{}};
  for (const name of peerNames) {{ have[name] = new Set(); inflight[name] = new Set(); downloaded[name] = 0; }}
  for (const ev of allEvents) {{
    if (ev.t > t) break;
    const owner = ev.owner;
    if (ev.kind === 'start' && ev.have_all) {{
      // A seed starts already holding every piece — it never emits
      // 'piece_complete' events for pieces it never had to download, so
      // without this its row would misleadingly show as all-missing.
      for (let i = 0; i < torrent.num_pieces; i++) have[owner].add(i);
    }} else if (ev.kind === 'piece_complete') {{
      have[owner].add(ev.index);
      inflight[owner].delete(ev.index);
    }} else if (ev.kind === 'block_received') {{
      if (!have[owner].has(ev.index)) inflight[owner].add(ev.index);
      downloaded[owner] += ev.length;
    }}
  }}
  return {{have, inflight, downloaded}};
}}

const svgNS = 'http://www.w3.org/2000/svg';
const chart = document.getElementById('ratechart');
const colors = ['#4f9cff', '#33c17a', '#ffb454', '#ff6f91', '#b892ff', '#5ad1e6'];

function render(t) {{
  document.getElementById('tlabel').textContent = `t=${{t.toFixed(1)}}s`;
  const {{have, inflight, downloaded}} = computeStateAt(t);
  for (const name of peerNames) {{
    const cells = cellsByPeer[name];
    for (let i = 0; i < cells.length; i++) {{
      cells[i].className = 'cell' + (have[name].has(i) ? ' have' : (inflight[name].has(i) ? ' inflight' : ''));
    }}
  }}

  // Rate chart: cumulative downloaded bytes per peer, plotted up to t.
  while (chart.firstChild) chart.removeChild(chart.firstChild);
  let maxBytes = 1;
  const series = {{}};
  for (const name of peerNames) {{
    let cum = 0;
    const pts = [[0, 0]];
    for (const ev of allEvents) {{
      if (ev.owner !== name || ev.kind !== 'block_received' || ev.t > t) continue;
      cum += ev.length;
      pts.push([ev.t, cum]);
    }}
    pts.push([t, cum]);
    series[name] = pts;
    maxBytes = Math.max(maxBytes, cum);
  }}
  let ci = 0;
  for (const name of peerNames) {{
    const pts = series[name];
    const path = pts.map(([pt, b], i) =>
      `${{i === 0 ? 'M' : 'L'}} ${{(pt / Math.max(t, 0.001) * 580 + 10).toFixed(1)}} ${{(150 - b / maxBytes * 140).toFixed(1)}}`
    ).join(' ');
    const el = document.createElementNS(svgNS, 'path');
    el.setAttribute('d', path);
    el.setAttribute('fill', 'none');
    el.setAttribute('stroke', colors[ci % colors.length]);
    el.setAttribute('stroke-width', '2');
    chart.appendChild(el);
    ci++;
  }}

  const listEl = document.getElementById('eventlist');
  const recent = allEvents.filter(e => e.t <= t).slice(-60);
  listEl.innerHTML = recent.map(e => {{
    const rest = Object.keys(e).filter(k => !['t','kind','owner'].includes(k))
      .map(k => `${{k}}=${{JSON.stringify(e[k])}}`).join(' ');
    return `[${{e.t.toFixed(2)}}s] ${{e.owner}}: ${{e.kind}} ${{rest}}`;
  }}).join('<br>');
  listEl.scrollTop = listEl.scrollHeight;
}}

const scrubber = document.getElementById('scrubber');
scrubber.max = String(Math.ceil(maxT * 10));
scrubber.addEventListener('input', () => render(Number(scrubber.value) / 10));

let playing = false, playTimer = null;
document.getElementById('playbtn').addEventListener('click', (e) => {{
  playing = !playing;
  e.target.textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing) {{
    if (Number(scrubber.value) >= Number(scrubber.max)) scrubber.value = 0;
    playTimer = setInterval(() => {{
      let v = Number(scrubber.value) + 2;
      if (v >= Number(scrubber.max)) {{ v = Number(scrubber.max); playing = false; e.target.textContent = '▶ Play'; clearInterval(playTimer); }}
      scrubber.value = v;
      render(v / 10);
    }}, 60);
  }} else {{
    clearInterval(playTimer);
  }}
}});

render(0);
</script>
</body>
</html>
"""
