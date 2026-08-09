"""Renders a TraceRecorder's event log into a single self-contained HTML
file: cwnd/ssthresh sawtooth, RTT/RTO over time, and a send/retransmit/
drop sequence timeline, plus a summary stat table. No external JS/CSS —
everything (including the chart drawing) is inlined so the file opens
standalone in any browser.
"""

import json


def _summarize(events, side_filter=None):
    evs = [e for e in events if side_filter is None or e["side"] == side_filter]
    counts = {}
    for e in evs:
        counts[e["event"]] = counts.get(e["event"], 0) + 1
    sent_bytes = sum(e.get("length", 0) for e in evs if e["event"] == "send")
    duration = max((e["t"] for e in events), default=0.0)
    return {
        "event_counts": counts,
        "sent_bytes": sent_bytes,
        "duration_s": duration,
        "throughput_kibps": (sent_bytes / 1024 / duration) if duration > 0 else 0.0,
    }


def render_html(events, title="Conduit trace report", subtitle="") -> str:
    summary = {
        "client": _summarize(events, "client"),
        "server": _summarize(events, "server"),
        "netsim": _summarize(events, "netsim"),
        "overall_duration_s": max((e["t"] for e in events), default=0.0),
    }
    data_json = json.dumps(events)
    summary_json = json.dumps(summary)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{_escape(title)}</title>
<style>
  :root {{
    --bg: #0b0f14; --panel: #121822; --border: #223047; --text: #d7e3f4;
    --muted: #7f93ad; --accent: #4fd1c5; --accent2: #f6ad55; --danger: #fc8181;
    --grid: #1c2634;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem; background: var(--bg); color: var(--text);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}
  h1 {{ font-size: 1.4rem; margin: 0 0 0.25rem; }}
  .subtitle {{ color: var(--muted); margin-bottom: 1.5rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.75rem; margin-bottom: 2rem; }}
  .tile {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 1rem; }}
  .tile .label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .tile .value {{ font-size: 1.4rem; margin-top: 0.25rem; }}
  .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1.5rem; }}
  .panel h2 {{ font-size: 1rem; margin: 0 0 0.75rem; color: var(--accent); }}
  svg {{ width: 100%; height: 220px; display: block; }}
  .legend {{ display: flex; gap: 1.25rem; margin-top: 0.5rem; font-size: 0.8rem; color: var(--muted); flex-wrap: wrap; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
  .swatch {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
  .tooltip {{
    position: fixed; pointer-events: none; background: #000c; border: 1px solid var(--border);
    border-radius: 4px; padding: 0.35rem 0.6rem; font-size: 0.75rem; display: none; z-index: 10;
    white-space: nowrap;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 0.3rem 0.6rem; border-bottom: 1px solid var(--grid); }}
  th {{ color: var(--muted); font-weight: normal; }}
</style>
</head>
<body>
<h1>{_escape(title)}</h1>
<div class="subtitle">{_escape(subtitle)}</div>

<div class="grid" id="tiles"></div>

<div class="panel">
  <h2>Congestion window / ssthresh over time (client)</h2>
  <svg id="chart-cwnd" viewBox="0 0 1000 220" preserveAspectRatio="none"></svg>
  <div class="legend">
    <span><span class="swatch" style="background:#4fd1c5"></span>cwnd (bytes)</span>
    <span><span class="swatch" style="background:#f6ad55"></span>ssthresh (bytes)</span>
    <span><span class="swatch" style="background:#fc8181"></span>timeout</span>
    <span><span class="swatch" style="background:#f687b3"></span>fast retransmit</span>
  </div>
</div>

<div class="panel">
  <h2>RTT samples &amp; RTO over time (client)</h2>
  <svg id="chart-rtt" viewBox="0 0 1000 220" preserveAspectRatio="none"></svg>
  <div class="legend">
    <span><span class="swatch" style="background:#4fd1c5"></span>RTT sample</span>
    <span><span class="swatch" style="background:#f6ad55"></span>RTO</span>
  </div>
</div>

<div class="panel">
  <h2>Sequence timeline</h2>
  <svg id="chart-seq" viewBox="0 0 1000 220" preserveAspectRatio="none"></svg>
  <div class="legend">
    <span><span class="swatch" style="background:#4fd1c5"></span>client send</span>
    <span><span class="swatch" style="background:#63b3ed"></span>server send</span>
    <span><span class="swatch" style="background:#f687b3"></span>retransmit</span>
    <span><span class="swatch" style="background:#fc8181"></span>netsim drop</span>
    <span><span class="swatch" style="background:#f6ad55"></span>netsim reorder</span>
  </div>
</div>

<div class="panel">
  <h2>Event counts</h2>
  <table id="event-table"></table>
</div>

<div class="tooltip" id="tooltip"></div>

<script id="trace-data" type="application/json">{data_json}</script>
<script id="trace-summary" type="application/json">{summary_json}</script>
<script>
const EVENTS = JSON.parse(document.getElementById('trace-data').textContent);
const SUMMARY = JSON.parse(document.getElementById('trace-summary').textContent);
const NS = 'http://www.w3.org/2000/svg';

function el(tag, attrs) {{
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}}

function tile(label, value) {{
  const d = document.createElement('div');
  d.className = 'tile';
  d.innerHTML = `<div class="label">${{label}}</div><div class="value">${{value}}</div>`;
  return d;
}}

const tiles = document.getElementById('tiles');
tiles.appendChild(tile('Duration', SUMMARY.overall_duration_s.toFixed(2) + ' s'));
tiles.appendChild(tile('Client bytes sent', SUMMARY.client.sent_bytes.toLocaleString()));
tiles.appendChild(tile('Client throughput', SUMMARY.client.throughput_kibps.toFixed(1) + ' KiB/s'));
tiles.appendChild(tile('Retransmits', (SUMMARY.client.event_counts.retransmit || 0)));
tiles.appendChild(tile('Timeouts', (SUMMARY.client.event_counts.timeout || 0)));
tiles.appendChild(tile('Fast retransmits', (SUMMARY.client.event_counts.fast_retransmit || 0)));
tiles.appendChild(tile('Netsim dropped', (SUMMARY.netsim.event_counts.netsim_drop || 0)));
tiles.appendChild(tile('Netsim duplicated', (SUMMARY.netsim.event_counts.netsim_dup || 0)));
tiles.appendChild(tile('Netsim reordered', (SUMMARY.netsim.event_counts.netsim_reorder || 0)));

const table = document.getElementById('event-table');
const allCounts = {{}};
for (const side of ['client', 'server', 'netsim']) {{
  for (const [k, v] of Object.entries(SUMMARY[side].event_counts)) {{
    allCounts[k] = allCounts[k] || {{}};
    allCounts[k][side] = v;
  }}
}}
let rows = '<tr><th>event</th><th>client</th><th>server</th><th>netsim</th></tr>';
for (const k of Object.keys(allCounts).sort()) {{
  const c = allCounts[k];
  rows += `<tr><td>${{k}}</td><td>${{c.client||0}}</td><td>${{c.server||0}}</td><td>${{c.netsim||0}}</td></tr>`;
}}
table.innerHTML = rows;

const tooltip = document.getElementById('tooltip');
function showTooltip(evt, text) {{
  tooltip.style.display = 'block';
  tooltip.style.left = (evt.clientX + 12) + 'px';
  tooltip.style.top = (evt.clientY + 12) + 'px';
  tooltip.textContent = text;
}}
function hideTooltip() {{ tooltip.style.display = 'none'; }}

const W = 1000, H = 220, PAD = 30;
const maxT = Math.max(1e-6, SUMMARY.overall_duration_s);

function xOf(t) {{ return PAD + (t / maxT) * (W - 2 * PAD); }}
function yOf(v, maxV) {{ return H - PAD - (v / Math.max(1, maxV)) * (H - 2 * PAD); }}

function axes(svg, maxV, vLabel) {{
  svg.appendChild(el('line', {{x1: PAD, y1: H - PAD, x2: W - PAD, y2: H - PAD, stroke: '#223047'}}));
  svg.appendChild(el('line', {{x1: PAD, y1: PAD, x2: PAD, y2: H - PAD, stroke: '#223047'}}));
  const t = el('text', {{x: PAD, y: 15, fill: '#7f93ad', 'font-size': 10}});
  t.textContent = vLabel + ' (max ' + Math.round(maxV).toLocaleString() + ')';
  svg.appendChild(t);
  const t2 = el('text', {{x: W - PAD, y: H - 8, fill: '#7f93ad', 'font-size': 10, 'text-anchor': 'end'}});
  t2.textContent = maxT.toFixed(2) + 's';
  svg.appendChild(t2);
}}

function polyline(svg, points, color, width) {{
  if (points.length < 2) return;
  const d = points.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  svg.appendChild(el('polyline', {{points: d, fill: 'none', stroke: color, 'stroke-width': width || 1.5}}));
}}

function dot(svg, x, y, color, r, label) {{
  const c = el('circle', {{cx: x, cy: y, r: r || 2.5, fill: color}});
  c.addEventListener('mousemove', (e) => showTooltip(e, label));
  c.addEventListener('mouseleave', hideTooltip);
  svg.appendChild(c);
}}

// --- cwnd / ssthresh chart ---
(function() {{
  const svg = document.getElementById('chart-cwnd');
  const cwndEvs = EVENTS.filter(e => e.side === 'client' && e.event === 'cwnd');
  const maxCwnd = Math.max(1, ...cwndEvs.map(e => Math.max(e.cwnd || 0, e.ssthresh || 0)));
  axes(svg, maxCwnd, 'bytes');
  polyline(svg, cwndEvs.map(e => [xOf(e.t), yOf(e.cwnd, maxCwnd)]), '#4fd1c5', 1.5);
  polyline(svg, cwndEvs.map(e => [xOf(e.t), yOf(Math.min(e.ssthresh, maxCwnd), maxCwnd)]), '#f6ad55', 1);
  for (const e of EVENTS.filter(e => e.side === 'client' && e.event === 'timeout')) {{
    svg.appendChild(el('line', {{x1: xOf(e.t), y1: PAD, x2: xOf(e.t), y2: H - PAD, stroke: '#fc8181', 'stroke-width': 1, 'stroke-dasharray': '2,2'}}));
  }}
  for (const e of EVENTS.filter(e => e.side === 'client' && e.event === 'fast_retransmit')) {{
    dot(svg, xOf(e.t), H - PAD, '#f687b3', 3, 'fast retransmit @ ' + e.t.toFixed(3) + 's seq=' + e.seq);
  }}
}})();

// --- RTT / RTO chart ---
(function() {{
  const svg = document.getElementById('chart-rtt');
  const rttEvs = EVENTS.filter(e => e.side === 'client' && e.event === 'rtt_sample');
  const maxRtt = Math.max(0.05, ...rttEvs.map(e => Math.max(e.rtt || 0, e.rto || 0)));
  axes(svg, maxRtt * 1000, 'ms');
  polyline(svg, rttEvs.map(e => [xOf(e.t), yOf(e.rtt * 1000, maxRtt * 1000)]), '#4fd1c5', 1.5);
  polyline(svg, rttEvs.map(e => [xOf(e.t), yOf(e.rto * 1000, maxRtt * 1000)]), '#f6ad55', 1);
}})();

// --- sequence timeline ---
(function() {{
  const svg = document.getElementById('chart-seq');
  const sendEvs = EVENTS.filter(e => e.event === 'send' && e.length > 0);
  const maxSeq = Math.max(1, ...sendEvs.map(e => e.seq || 0));
  axes(svg, maxSeq, 'seq');
  for (const e of sendEvs) {{
    const color = e.side === 'client' ? '#4fd1c5' : '#63b3ed';
    dot(svg, xOf(e.t), yOf(e.seq, maxSeq), color, 1.8, `${{e.side}} send seq=${{e.seq}} @ ${{e.t.toFixed(3)}}s`);
  }}
  for (const e of EVENTS.filter(e => e.event === 'retransmit')) {{
    dot(svg, xOf(e.t), yOf(e.seq, maxSeq), '#f687b3', 3, `retransmit seq=${{e.seq}} @ ${{e.t.toFixed(3)}}s`);
  }}
  for (const e of EVENTS.filter(e => e.event === 'netsim_drop')) {{
    dot(svg, xOf(e.t), H - PAD + 6, '#fc8181', 2.5, `netsim drop (${{e.direction}}) @ ${{e.t.toFixed(3)}}s`);
  }}
  for (const e of EVENTS.filter(e => e.event === 'netsim_reorder')) {{
    dot(svg, xOf(e.t), H - PAD + 14, '#f6ad55', 2.5, `netsim reorder (${{e.direction}}) @ ${{e.t.toFixed(3)}}s`);
  }}
}})();
</script>
</body>
</html>
"""


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_to_file(events, out_path, title="Conduit trace report", subtitle=""):
    html = render_html(events, title=title, subtitle=subtitle)
    with open(out_path, "w") as f:
        f.write(html)
    return out_path
