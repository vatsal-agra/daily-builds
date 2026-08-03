"""Turn a real recorded Undertow transfer's event log into a self-contained
interactive HTML report: a packet timeline swimlane (sent/acked/retransmitted),
a cwnd/ssthresh sawtooth chart, and a throughput-over-time chart. All data
embedded is from an actual run — nothing here is synthesized or idealized.
"""
import html
import json
import os


def _cwnd_series(sender_events):
    points = []
    for e in sender_events:
        if e["kind"] in ("segment_sent", "ack_advance", "retransmit") and "cwnd" in e:
            points.append({"t": e["t"], "cwnd": e["cwnd"], "ssthresh": e.get("ssthresh"), "kind": e["kind"]})
    return points


def _throughput_series(sender_events, bucket=0.5):
    acked_bytes_by_bucket = {}
    last_ack = None
    for e in sender_events:
        if e["kind"] != "ack_advance":
            continue
        ack = e.get("ack")
        if ack is None:
            continue
        if last_ack is not None and ack > last_ack:
            b = int(e["t"] // bucket)
            acked_bytes_by_bucket[b] = acked_bytes_by_bucket.get(b, 0) + (ack - last_ack)
        last_ack = ack
    if not acked_bytes_by_bucket:
        return []
    max_bucket = max(acked_bytes_by_bucket)
    return [
        {"t": b * bucket, "kbps": acked_bytes_by_bucket.get(b, 0) / 1024.0 / bucket}
        for b in range(max_bucket + 1)
    ]


def _timeline_points(sender_events):
    points = []
    for e in sender_events:
        if e["kind"] in ("segment_sent", "retransmit", "ack_advance", "dup_ack"):
            points.append({"t": e["t"], "kind": e["kind"], "seq": e.get("seq") or e.get("ack")})
    return points


def generate_report(sender_events, receiver_events, netsim_stats, out_path, label=""):
    data = {
        "label": label,
        "cwnd": _cwnd_series(sender_events),
        "throughput": _throughput_series(sender_events),
        "timeline": _timeline_points(sender_events),
        "netsim_stats": netsim_stats,
        "counts": {
            "segments_sent": sum(1 for e in sender_events if e["kind"] == "segment_sent"),
            "retransmits": sum(1 for e in sender_events if e["kind"] == "retransmit"),
            "dup_acks": sum(1 for e in sender_events if e["kind"] == "dup_ack"),
            "acks": sum(1 for e in sender_events if e["kind"] == "ack_advance"),
        },
    }
    payload = json.dumps(data)
    title = html.escape(f"Undertow transfer report — {label}" if label else "Undertow transfer report")

    doc = TEMPLATE.replace("__TITLE__", title).replace("__DATA__", payload)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(doc)
    return out_path


TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 2rem; background: #0b0e14; color: #e6e6e6;
  }
  @media (prefers-color-scheme: light) {
    body { background: #f7f7fa; color: #1a1a1a; }
  }
  h1 { font-size: 1.3rem; margin-bottom: 0.2rem; }
  .sub { opacity: 0.7; margin-bottom: 1.5rem; font-size: 0.9rem; }
  .stats { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 2rem; }
  .stat {
    background: rgba(127,127,127,0.12); border-radius: 10px; padding: 0.75rem 1.1rem;
    min-width: 120px;
  }
  .stat .val { font-size: 1.4rem; font-weight: 600; }
  .stat .lbl { font-size: 0.75rem; opacity: 0.7; text-transform: uppercase; letter-spacing: 0.04em; }
  .panel {
    background: rgba(127,127,127,0.08); border-radius: 14px; padding: 1.2rem 1.4rem;
    margin-bottom: 1.6rem; overflow-x: auto;
  }
  .panel h2 { font-size: 1rem; margin: 0 0 0.8rem 0; }
  svg { display: block; }
  .axis-label { font-size: 10px; opacity: 0.6; }
  .legend { font-size: 0.8rem; opacity: 0.85; margin-top: 0.5rem; display: flex; gap: 1.2rem; flex-wrap: wrap; }
  .legend span { display: inline-flex; align-items: center; gap: 0.4rem; }
  .swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
</style>
</head>
<body>
<h1>Undertow transfer report</h1>
<div class="sub" id="subtitle"></div>
<div class="stats" id="stats"></div>

<div class="panel">
  <h2>Congestion window (cwnd) &amp; slow-start threshold over time</h2>
  <svg id="cwndChart" width="900" height="260"></svg>
  <div class="legend">
    <span><span class="swatch" style="background:#5aa9e6"></span> cwnd</span>
    <span><span class="swatch" style="background:#e6a15a"></span> ssthresh</span>
    <span><span class="swatch" style="background:#e65a5a"></span> retransmit event</span>
  </div>
</div>

<div class="panel">
  <h2>Throughput over time (0.5s buckets, from cumulative ACKs)</h2>
  <svg id="throughputChart" width="900" height="200"></svg>
</div>

<div class="panel">
  <h2>Packet timeline</h2>
  <svg id="timelineChart" width="900" height="160"></svg>
  <div class="legend">
    <span><span class="swatch" style="background:#5aa9e6"></span> sent</span>
    <span><span class="swatch" style="background:#5ae67e"></span> ack advance</span>
    <span><span class="swatch" style="background:#e6d75a"></span> dup ack</span>
    <span><span class="swatch" style="background:#e65a5a"></span> retransmit</span>
  </div>
</div>

<script>
const DATA = __DATA__;

document.getElementById('subtitle').textContent =
  (DATA.label ? DATA.label + " — " : "") +
  DATA.counts.segments_sent + " segments sent, " +
  DATA.counts.retransmits + " retransmits, " +
  DATA.counts.dup_acks + " dup ACKs, netsim dropped " +
  DATA.netsim_stats.dropped + "/" + (DATA.netsim_stats.forwarded + DATA.netsim_stats.dropped);

const statsEl = document.getElementById('stats');
const statDefs = [
  ["Segments sent", DATA.counts.segments_sent],
  ["Retransmits", DATA.counts.retransmits],
  ["Dup ACKs", DATA.counts.dup_acks],
  ["Packets dropped (net)", DATA.netsim_stats.dropped],
  ["Packets duplicated (net)", DATA.netsim_stats.duplicated],
  ["Packets reordered (net)", DATA.netsim_stats.reordered],
];
for (const [label, val] of statDefs) {
  const d = document.createElement('div');
  d.className = 'stat';
  d.innerHTML = '<div class="val">' + val + '</div><div class="lbl">' + label + '</div>';
  statsEl.appendChild(d);
}

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function drawCwndChart() {
  const svg = document.getElementById('cwndChart');
  const W = 900, H = 260, padL = 50, padB = 30, padT = 10, padR = 10;
  const pts = DATA.cwnd;
  if (!pts.length) return;
  const maxT = Math.max(...pts.map(p => p.t), 0.1);
  // ssthresh starts at a large placeholder value (effectively "unbounded
  // until slow start needs a ceiling") and only becomes a meaningful,
  // small number after the first loss event. Scaling the y-axis to that
  // initial placeholder squashes the entire, actually-interesting cwnd
  // sawtooth into a thin line near zero — caught by actually rendering
  // this chart, not just generating it. Scale off cwnd (what genuinely
  // varies throughout) and clamp ssthresh's plotted line to that range.
  const maxY = Math.max(...pts.map(p => p.cwnd), 10) * 1.15;
  const x = t => padL + (t / maxT) * (W - padL - padR);
  const y = v => H - padB - (Math.min(v, maxY) / maxY) * (H - padT - padB);

  svg.appendChild(svgEl('line', {x1: padL, y1: H-padB, x2: W-padR, y2: H-padB, stroke: 'currentColor', opacity: 0.3}));
  svg.appendChild(svgEl('line', {x1: padL, y1: padT, x2: padL, y2: H-padB, stroke: 'currentColor', opacity: 0.3}));

  function pathFor(key, color) {
    let d = '';
    pts.forEach((p, i) => {
      if (p[key] == null) return;
      d += (d ? 'L' : 'M') + x(p.t).toFixed(1) + ',' + y(p[key]).toFixed(1) + ' ';
    });
    svg.appendChild(svgEl('path', {d, fill: 'none', stroke: color, 'stroke-width': 1.6}));
  }
  pathFor('ssthresh', '#e6a15a');
  pathFor('cwnd', '#5aa9e6');

  pts.filter(p => p.kind === 'retransmit').forEach(p => {
    svg.appendChild(svgEl('circle', {cx: x(p.t), cy: y(p.cwnd), r: 2.5, fill: '#e65a5a'}));
  });

  for (let i = 0; i <= 4; i++) {
    const v = Math.round(maxY * i / 4);
    const ty = y(v);
    const t = svgEl('text', {x: 4, y: ty + 3, class: 'axis-label'});
    t.textContent = v;
    svg.appendChild(t);
  }
  for (let i = 0; i <= 5; i++) {
    const tv = (maxT * i / 5);
    const tx = x(tv);
    const t = svgEl('text', {x: tx - 8, y: H - 8, class: 'axis-label'});
    t.textContent = tv.toFixed(1) + 's';
    svg.appendChild(t);
  }
}

function drawThroughputChart() {
  const svg = document.getElementById('throughputChart');
  const W = 900, H = 200, padL = 50, padB = 30, padT = 10, padR = 10;
  const pts = DATA.throughput;
  if (!pts.length) return;
  const maxT = Math.max(...pts.map(p => p.t), 0.1);
  const maxY = Math.max(...pts.map(p => p.kbps), 1);
  const x = t => padL + (t / maxT) * (W - padL - padR);
  const y = v => H - padB - (v / maxY) * (H - padT - padB);
  const barW = Math.max(1, (W - padL - padR) / pts.length - 1);

  svg.appendChild(svgEl('line', {x1: padL, y1: H-padB, x2: W-padR, y2: H-padB, stroke: 'currentColor', opacity: 0.3}));
  pts.forEach(p => {
    svg.appendChild(svgEl('rect', {
      x: x(p.t), y: y(p.kbps), width: barW, height: (H - padB) - y(p.kbps),
      fill: '#5aa9e6', opacity: 0.85,
    }));
  });
  for (let i = 0; i <= 4; i++) {
    const v = (maxY * i / 4);
    const t = svgEl('text', {x: 4, y: y(v) + 3, class: 'axis-label'});
    t.textContent = v.toFixed(0) + ' KB/s';
    svg.appendChild(t);
  }
}

function drawTimeline() {
  const svg = document.getElementById('timelineChart');
  const W = 900, H = 160, padL = 50, padB = 20, padT = 20, padR = 10;
  const pts = DATA.timeline;
  if (!pts.length) return;
  const maxT = Math.max(...pts.map(p => p.t), 0.1);
  const x = t => padL + (t / maxT) * (W - padL - padR);
  const lanes = {segment_sent: [padT+10, '#5aa9e6'], ack_advance: [padT+45, '#5ae67e'],
                 dup_ack: [padT+80, '#e6d75a'], retransmit: [padT+115, '#e65a5a']};
  const labels = {segment_sent: 'sent', ack_advance: 'ack', dup_ack: 'dup-ack', retransmit: 'retransmit'};
  Object.keys(lanes).forEach(kind => {
    const [ly, color] = lanes[kind];
    svg.appendChild(svgEl('text', {x: 4, y: ly + 3, class: 'axis-label'})).textContent = labels[kind];
  });
  pts.forEach(p => {
    const lane = lanes[p.kind];
    if (!lane) return;
    svg.appendChild(svgEl('circle', {cx: x(p.t), cy: lane[0], r: 1.8, fill: lane[1], opacity: 0.8}));
  });
}

drawCwndChart();
drawThroughputChart();
drawTimeline();
</script>
</body>
</html>
"""
