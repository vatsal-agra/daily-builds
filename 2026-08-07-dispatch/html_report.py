"""Self-contained interactive HTML visualizer: Gantt charts per CPU-scheduling
algorithm, a multi-metric comparison grid, an animated VM frame-by-frame replay,
and a Belady's-Anomaly fault-count-vs-frames line chart. No client-side scheduling
or page-replacement logic — the HTML holds only the real, already-computed results
of core/scheduler.py and core/vm.py, embedded as JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

from core import metrics as metrics_mod
from core import vm as vm_mod


def _schedule_to_json(schedule):
    return {
        "algorithm": schedule.algorithm,
        "gantt": [{"pid": pid, "start": start, "end": end} for pid, start, end in schedule.gantt],
        "results": [r.as_dict() for r in sorted(schedule.results.values(), key=lambda r: r.pid)],
        "metrics": metrics_mod.aggregate(schedule),
    }


def _trace_to_json(trace):
    return {
        "algorithm": trace.algorithm,
        "num_frames": trace.num_frames,
        "ref_string": trace.ref_string,
        "faults": trace.faults,
        "hits": trace.hits,
        "steps": [
            {"index": s.index, "page": s.page, "frames": s.frames, "fault": s.fault, "evicted": s.evicted}
            for s in trace.steps
        ],
    }


def build_report(processes, quantum, ref_string, frames, output_path):
    rows, runs = metrics_mod.compare(processes, quantum=quantum)
    cpu_payload = [_schedule_to_json(s) for s in runs]

    vm_payload = {name: _trace_to_json(fn(ref_string, frames)) for name, fn in vm_mod.ALGORITHMS.items()}

    unique_pages = len(set(ref_string))
    max_sweep = max(2, min(8, unique_pages + 2))
    anomaly_payload = {
        "frame_range": list(range(1, max_sweep + 1)),
        "series": {
            name: [fn(ref_string, f).faults for f in range(1, max_sweep + 1)]
            for name, fn in vm_mod.ALGORITHMS.items()
        },
        "ref_string": ref_string,
    }

    payload = {"cpu": cpu_payload, "vm": vm_payload, "anomaly": anomaly_payload,
               "vm_frames": frames, "quantum": quantum}
    data_json = json.dumps(payload).replace("</", "<\\/")

    html = _TEMPLATE.replace("__DISPATCH_DATA__", data_json)
    out = Path(output_path)
    out.write_text(html)
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dispatch — OS Scheduling &amp; Virtual Memory Report</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  .viz-root {
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --grid:           #e1e0d9;
    --axis:           #c3c2b7;
    --border:         rgba(11,11,11,0.10);
    --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
    --series-5: #e87ba4; --series-6: #008300; --series-7: #4a3aa7; --series-8: #e34948;
    --good: #0ca30c; --idle: #d8d6cc;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff; --text-secondary: #c3c2b7;
      --text-muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
      --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
      --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
      --idle: #383835;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff; --text-secondary: #c3c2b7;
    --text-muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
    --idle: #383835;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--page); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  .viz-root { background: var(--page); color: var(--text-primary); padding: 24px; max-width: 1180px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin: 0 0 4px; }
  h2 { font-size: 1.125rem; margin: 32px 0 10px; border-bottom: 1px solid var(--grid); padding-bottom: 6px; }
  .subtitle { color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 20px; }
  .panel { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; margin-bottom: 16px; }
  .tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
  .tab-btn { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-secondary);
             padding: 6px 12px; border-radius: 999px; font-size: 0.82rem; cursor: pointer; }
  .tab-btn.active { background: var(--series-1); color: white; border-color: var(--series-1); }
  .tab-btn:hover:not(.active) { color: var(--text-primary); }
  svg text { fill: var(--text-secondary); font-size: 11px; font-family: inherit; }
  svg .axis-line { stroke: var(--axis); stroke-width: 1; }
  svg .grid-line { stroke: var(--grid); stroke-width: 1; }
  .gbar { cursor: pointer; }
  .gbar:hover { filter: brightness(1.12); }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0 4px; font-size: 0.8rem; color: var(--text-secondary); }
  .legend-item { display: flex; align-items: center; gap: 5px; }
  .legend-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  table { border-collapse: collapse; width: 100%; font-size: 0.82rem; margin-top: 6px; }
  th, td { text-align: right; padding: 4px 8px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--text-muted); font-weight: 600; }
  .tooltip { position: fixed; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
             padding: 6px 9px; border-radius: 6px; font-size: 0.78rem; opacity: 0; transition: opacity .08s;
             z-index: 50; white-space: nowrap; }
  .tooltip.show { opacity: 0.96; }
  .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
  .controls { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  button.ctl { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
               padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 0.82rem; }
  button.ctl:hover { border-color: var(--series-1); }
  .frame-cell { fill: var(--idle); stroke: var(--border); }
  .frame-cell.fault { fill: var(--series-8); }
  .frame-cell.hit { fill: var(--series-3); }
  .mem-scrub { width: 100%; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.75rem; margin-left: 8px; }
  .badge.anomaly { background: var(--series-8); color: white; }
  .badge.ok { background: var(--good); color: white; }
  footer { color: var(--text-muted); font-size: 0.78rem; margin-top: 28px; text-align: center; }
</style>
</head>
<body>
<div class="viz-root">
  <h1>Dispatch</h1>
  <div class="subtitle">CPU scheduling &amp; virtual memory — real simulation output, computed server-side, rendered here.</div>

  <h2>CPU scheduling — Gantt charts</h2>
  <div class="panel">
    <div class="tabs" id="cpu-tabs"></div>
    <div id="cpu-gantt"></div>
    <div id="cpu-table"></div>
  </div>

  <h2>Algorithm comparison</h2>
  <div class="panel">
    <div class="metric-grid" id="cmp-grid"></div>
  </div>

  <h2>Virtual memory — page replacement</h2>
  <div class="panel">
    <div class="tabs" id="vm-tabs"></div>
    <div class="controls">
      <button class="ctl" id="vm-play">▶ Play</button>
      <button class="ctl" id="vm-step">Step</button>
      <button class="ctl" id="vm-reset">⟲ Reset</button>
      <input type="range" class="mem-scrub" id="vm-scrub" min="0" value="0">
      <span id="vm-status" style="font-size:0.82rem;color:var(--text-secondary)"></span>
    </div>
    <div id="vm-anim"></div>
  </div>

  <h2>Belady's Anomaly — fault count vs. frame count</h2>
  <div class="panel">
    <div id="anomaly-chart"></div>
    <div id="anomaly-note" style="font-size:0.85rem;color:var(--text-secondary);margin-top:6px;"></div>
  </div>

  <footer>Dispatch — generated report. All numbers are real simulator output, not illustrative placeholders.</footer>
</div>
<div class="tooltip" id="tooltip"></div>

<script>
const DATA = __DISPATCH_DATA__;
const SERIES_COLORS = ["--series-1","--series-2","--series-3","--series-4","--series-5","--series-6","--series-7","--series-8"];
const root = document.documentElement;
function cssVar(name) { return getComputedStyle(document.querySelector(".viz-root")).getPropertyValue(name).trim(); }
const tooltip = document.getElementById("tooltip");
function showTip(evt, html) {
  tooltip.innerHTML = html;
  tooltip.style.left = (evt.clientX + 14) + "px";
  tooltip.style.top = (evt.clientY + 14) + "px";
  tooltip.classList.add("show");
}
function hideTip() { tooltip.classList.remove("show"); }

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

// ---- process pid -> stable color assignment across the whole report ----
const pidColorMap = {};
(function assignPidColors() {
  const pids = new Set();
  DATA.cpu.forEach(sched => sched.results.forEach(r => pids.add(r.pid)));
  Array.from(pids).sort().forEach((pid, i) => { pidColorMap[pid] = SERIES_COLORS[i % SERIES_COLORS.length]; });
})();

// =========================== CPU Gantt ===========================
let currentAlgoIdx = 0;
function renderCpuTabs() {
  const wrap = document.getElementById("cpu-tabs");
  wrap.innerHTML = "";
  DATA.cpu.forEach((sched, i) => {
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (i === currentAlgoIdx ? " active" : "");
    btn.textContent = sched.algorithm;
    btn.onclick = () => { currentAlgoIdx = i; renderCpuTabs(); renderGantt(); renderProcessTable(); };
    wrap.appendChild(btn);
  });
}

function renderGantt() {
  const sched = DATA.cpu[currentAlgoIdx];
  const container = document.getElementById("cpu-gantt");
  container.innerHTML = "";
  const makespan = sched.gantt.length ? sched.gantt[sched.gantt.length - 1].end : 1;
  const pids = sched.results.map(r => r.pid);
  const rowH = 28, rowGap = 6, leftPad = 60, topPad = 10, w = 1080;
  const plotW = w - leftPad - 20;
  const h = topPad + pids.length * (rowH + rowGap) + 30;
  const svg = svgEl("svg", {width: "100%", viewBox: `0 0 ${w} ${h}`, height: h});

  const legend = document.createElement("div");
  legend.className = "legend";
  pids.forEach(pid => {
    const item = document.createElement("div"); item.className = "legend-item";
    const sw = document.createElement("span"); sw.className = "legend-swatch";
    sw.style.background = `var(${pidColorMap[pid]})`;
    item.appendChild(sw);
    const label = document.createElement("span"); label.textContent = pid;
    item.appendChild(label);
    legend.appendChild(item);
  });
  container.appendChild(legend);

  const x = t => leftPad + (t / makespan) * plotW;
  // gridlines
  const nTicks = Math.min(makespan, 12);
  for (let i = 0; i <= nTicks; i++) {
    const t = Math.round((i / nTicks) * makespan);
    const gx = x(t);
    svg.appendChild(svgEl("line", {x1: gx, x2: gx, y1: topPad, y2: h - 20, class: "grid-line"}));
    const lbl = svgEl("text", {x: gx, y: h - 6, "text-anchor": "middle"});
    lbl.textContent = t;
    svg.appendChild(lbl);
  }

  pids.forEach((pid, rowIdx) => {
    const y = topPad + rowIdx * (rowH + rowGap);
    const label = svgEl("text", {x: leftPad - 8, y: y + rowH / 2 + 4, "text-anchor": "end"});
    label.textContent = pid;
    svg.appendChild(label);
    svg.appendChild(svgEl("line", {x1: leftPad, x2: w - 20, y1: y + rowH, y2: y + rowH, class: "grid-line"}));
  });

  sched.gantt.forEach(seg => {
    if (seg.pid === null) return;
    const rowIdx = pids.indexOf(seg.pid);
    const y = topPad + rowIdx * (rowH + rowGap);
    const rectX = x(seg.start), rectW = Math.max(1, x(seg.end) - x(seg.start));
    const rect = svgEl("rect", {
      x: rectX, y, width: rectW, height: rowH, rx: 4,
      fill: `var(${pidColorMap[seg.pid]})`, class: "gbar"
    });
    rect.addEventListener("mousemove", e => showTip(e, `<b>${seg.pid}</b><br>t=${seg.start}&ndash;${seg.end} (${seg.end-seg.start} units)`));
    rect.addEventListener("mouseleave", hideTip);
    svg.appendChild(rect);
  });

  container.appendChild(svg);
}

function renderProcessTable() {
  const sched = DATA.cpu[currentAlgoIdx];
  const div = document.getElementById("cpu-table");
  const m = sched.metrics;
  let html = `<table><thead><tr><th>pid</th><th>arrival</th><th>burst</th><th>start</th>
    <th>completion</th><th>waiting</th><th>turnaround</th><th>response</th></tr></thead><tbody>`;
  sched.results.forEach(r => {
    html += `<tr><td>${r.pid}</td><td>${r.arrival_time}</td><td>${r.burst_time}</td><td>${r.start_time}</td>
      <td>${r.completion_time}</td><td>${r.waiting_time}</td><td>${r.turnaround_time}</td><td>${r.response_time}</td></tr>`;
  });
  html += `</tbody></table><div style="margin-top:8px;font-size:0.82rem;color:var(--text-secondary)">
    avg waiting <b style="color:var(--text-primary)">${m.avg_waiting_time.toFixed(2)}</b> &nbsp;
    avg turnaround <b style="color:var(--text-primary)">${m.avg_turnaround_time.toFixed(2)}</b> &nbsp;
    avg response <b style="color:var(--text-primary)">${m.avg_response_time.toFixed(2)}</b> &nbsp;
    CPU util <b style="color:var(--text-primary)">${(m.cpu_utilization*100).toFixed(1)}%</b> &nbsp;
    context switches <b style="color:var(--text-primary)">${m.context_switches}</b></div>`;
  div.innerHTML = html;
}

// =========================== Comparison grid (small multiples, one metric per panel) ===========================
function renderComparisonGrid() {
  const grid = document.getElementById("cmp-grid");
  grid.innerHTML = "";
  const metricsSpec = [
    {key: "avg_waiting_time", label: "Avg waiting time", fmt: v => v.toFixed(2)},
    {key: "avg_turnaround_time", label: "Avg turnaround time", fmt: v => v.toFixed(2)},
    {key: "avg_response_time", label: "Avg response time", fmt: v => v.toFixed(2)},
    {key: "cpu_utilization", label: "CPU utilization", fmt: v => (v*100).toFixed(1) + "%"},
  ];
  const algos = DATA.cpu.map(s => s.algorithm);
  metricsSpec.forEach((spec, specIdx) => {
    const values = DATA.cpu.map(s => s.metrics[spec.key]);
    const maxV = Math.max(...values, 0.0001);
    const wrap = document.createElement("div");
    const title = document.createElement("div");
    title.style.cssText = "font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;";
    title.textContent = spec.label;
    wrap.appendChild(title);
    const barH = 20, gap = 6, w = 380, labelColW = 78, valueColW = 56;
    const h = algos.length * (barH + gap);
    const svg = svgEl("svg", {width: "100%", viewBox: `0 0 ${w} ${h}`, height: h});
    algos.forEach((alg, i) => {
      const y = i * (barH + gap);
      const bw = Math.max(2, (values[i] / maxV) * (w - labelColW - valueColW));
      const rect = svgEl("rect", {x: labelColW, y, width: bw, height: barH, rx: 3, fill: `var(${pidColorMap[alg] || SERIES_COLORS[i % 8]})`, class: "gbar"});
      rect.addEventListener("mousemove", e => showTip(e, `<b>${alg}</b><br>${spec.label}: ${spec.fmt(values[i])}`));
      rect.addEventListener("mouseleave", hideTip);
      svg.appendChild(rect);
      const lbl = svgEl("text", {x: labelColW - 4, y: y + barH/2 + 4, "text-anchor": "end"});
      lbl.textContent = alg.length > 12 ? alg.slice(0,11)+"…" : alg;
      svg.appendChild(lbl);
      const vlbl = svgEl("text", {x: labelColW + bw + 6, y: y + barH/2 + 4, "text-anchor": "start"});
      vlbl.textContent = spec.fmt(values[i]);
      vlbl.style.fill = "var(--text-primary)";
      svg.appendChild(vlbl);
    });
    wrap.appendChild(svg);
    grid.appendChild(wrap);
  });
}

// =========================== VM animation ===========================
let vmAlgo = Object.keys(DATA.vm)[0];
let vmIndex = 0;
let vmTimer = null;

function renderVmTabs() {
  const wrap = document.getElementById("vm-tabs");
  wrap.innerHTML = "";
  Object.keys(DATA.vm).forEach(name => {
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (name === vmAlgo ? " active" : "");
    btn.textContent = `${DATA.vm[name].algorithm} (${DATA.vm[name].faults} faults)`;
    btn.onclick = () => { vmAlgo = name; vmIndex = 0; renderVmTabs(); setupScrub(); renderVmFrame(); };
    wrap.appendChild(btn);
  });
}

function setupScrub() {
  const trace = DATA.vm[vmAlgo];
  const scrub = document.getElementById("vm-scrub");
  scrub.max = trace.steps.length - 1;
  scrub.value = vmIndex;
}

function renderVmFrame() {
  const trace = DATA.vm[vmAlgo];
  const container = document.getElementById("vm-anim");
  container.innerHTML = "";
  const step = trace.steps[vmIndex];
  document.getElementById("vm-scrub").value = vmIndex;
  document.getElementById("vm-status").textContent =
    `step ${vmIndex + 1}/${trace.steps.length} — ref=${step.page} — ${step.fault ? "FAULT" : "hit"}` +
    (step.evicted !== null && step.evicted !== undefined ? ` (evicted ${step.evicted})` : "");

  const cell = 46, gap = 8, top = 10;
  const w = Math.max(400, trace.num_frames * (cell + gap) + 20);
  const h = top + cell + 40;
  const svg = svgEl("svg", {width: "100%", viewBox: `0 0 ${w} ${h}`, height: h});
  step.frames.forEach((page, i) => {
    const x = 10 + i * (cell + gap);
    const cls = page === null ? "" : (step.fault && page === step.page ? "fault" : "hit");
    const rect = svgEl("rect", {x, y: top, width: cell, height: cell, rx: 6, class: "frame-cell " + cls});
    svg.appendChild(rect);
    const lbl = svgEl("text", {x: x + cell/2, y: top + cell/2 + 5, "text-anchor": "middle"});
    lbl.style.fill = page === null ? "var(--text-muted)" : "white";
    lbl.style.fontWeight = "600";
    lbl.textContent = page === null ? "·" : page;
    svg.appendChild(lbl);
    const flabel = svgEl("text", {x: x + cell/2, y: top + cell + 16, "text-anchor": "middle"});
    flabel.textContent = "f" + i;
    svg.appendChild(flabel);
  });
  container.appendChild(svg);

  // reference-string strip with a marker on the current position
  const stripWrap = document.createElement("div");
  stripWrap.style.cssText = "margin-top:10px;font-family:monospace;font-size:0.85rem;line-height:1.9;word-break:break-all;color:var(--text-secondary)";
  trace.ref_string.forEach((p, i) => {
    const span = document.createElement("span");
    span.textContent = p + " ";
    if (i === vmIndex) { span.style.cssText = "background:var(--series-1);color:white;border-radius:3px;padding:1px 3px;"; }
    else if (i < vmIndex) { span.style.opacity = "0.55"; }
    stripWrap.appendChild(span);
  });
  container.appendChild(stripWrap);
}

document.getElementById("vm-scrub").addEventListener("input", e => { vmIndex = parseInt(e.target.value, 10); renderVmFrame(); });
document.getElementById("vm-step").addEventListener("click", () => {
  const trace = DATA.vm[vmAlgo];
  vmIndex = Math.min(trace.steps.length - 1, vmIndex + 1);
  renderVmFrame();
});
document.getElementById("vm-reset").addEventListener("click", () => { vmIndex = 0; stopPlay(); renderVmFrame(); });
function stopPlay() { if (vmTimer) { clearInterval(vmTimer); vmTimer = null; document.getElementById("vm-play").textContent = "▶ Play"; } }
document.getElementById("vm-play").addEventListener("click", () => {
  if (vmTimer) { stopPlay(); return; }
  document.getElementById("vm-play").textContent = "⏸ Pause";
  vmTimer = setInterval(() => {
    const trace = DATA.vm[vmAlgo];
    if (vmIndex >= trace.steps.length - 1) { stopPlay(); return; }
    vmIndex++; renderVmFrame();
  }, 550);
});

// =========================== Belady's Anomaly chart ===========================
function renderAnomalyChart() {
  const container = document.getElementById("anomaly-chart");
  container.innerHTML = "";
  const range = DATA.anomaly.frame_range;
  const series = DATA.anomaly.series;
  const names = Object.keys(series);
  const allVals = names.flatMap(n => series[n]);
  const maxV = Math.max(...allVals, 1);
  const w = 760, h = 260, padL = 40, padB = 30, padT = 12, padR = 12;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const svg = svgEl("svg", {width: "100%", viewBox: `0 0 ${w} ${h}`, height: h});
  const x = i => padL + (i / (range.length - 1 || 1)) * plotW;
  const y = v => padT + plotH - (v / maxV) * plotH;

  for (let gy = 0; gy <= maxV; gy += Math.max(1, Math.ceil(maxV/6))) {
    const gyy = y(gy);
    svg.appendChild(svgEl("line", {x1: padL, x2: w - padR, y1: gyy, y2: gyy, class: "grid-line"}));
    const lbl = svgEl("text", {x: padL - 6, y: gyy + 4, "text-anchor": "end"});
    lbl.textContent = gy;
    svg.appendChild(lbl);
  }
  range.forEach((f, i) => {
    const lbl = svgEl("text", {x: x(i), y: h - 8, "text-anchor": "middle"});
    lbl.textContent = f;
    svg.appendChild(lbl);
  });
  const axisLbl = svgEl("text", {x: w/2, y: h - 20, "text-anchor": "middle"});
  axisLbl.style.fill = "var(--text-muted)"; axisLbl.textContent = "frame count →";
  svg.appendChild(axisLbl);

  const legend = document.createElement("div"); legend.className = "legend";
  names.forEach((name, si) => {
    const vals = series[name];
    let d = "";
    vals.forEach((v, i) => { d += (i === 0 ? "M" : "L") + x(i) + "," + y(v) + " "; });
    const path = svgEl("path", {d, fill: "none", stroke: `var(${SERIES_COLORS[si % 8]})`, "stroke-width": 2.5});
    svg.appendChild(path);
    vals.forEach((v, i) => {
      const dot = svgEl("circle", {cx: x(i), cy: y(v), r: 4, fill: `var(${SERIES_COLORS[si % 8]})`});
      dot.addEventListener("mousemove", e => showTip(e, `<b>${name.toUpperCase()}</b><br>${range[i]} frames &rarr; ${v} faults`));
      dot.addEventListener("mouseleave", hideTip);
      svg.appendChild(dot);
    });
    const item = document.createElement("div"); item.className = "legend-item";
    const sw = document.createElement("span"); sw.className = "legend-swatch"; sw.style.background = `var(${SERIES_COLORS[si % 8]})`;
    item.appendChild(sw);
    const label = document.createElement("span"); label.textContent = name.toUpperCase();
    item.appendChild(label);
    legend.appendChild(item);
  });
  container.appendChild(legend);
  container.appendChild(svg);

  // anomaly detection: does fifo's fault series ever increase as frames increase?
  const fifoVals = series["fifo"] || [];
  let anomalyFound = false, detail = "";
  for (let i = 1; i < fifoVals.length; i++) {
    if (fifoVals[i] > fifoVals[i-1]) { anomalyFound = true; detail = `${range[i-1]}→${range[i]} frames: ${fifoVals[i-1]}→${fifoVals[i]} faults`; break; }
  }
  const note = document.getElementById("anomaly-note");
  if (anomalyFound) {
    note.innerHTML = `<span class="badge anomaly">Belady's Anomaly present</span> FIFO fault count increases with more frames (${detail}) on this reference string. LRU and Optimal are stack algorithms and never do this — compare their lines above.`;
  } else {
    note.innerHTML = `<span class="badge ok">monotonic</span> FIFO's fault count never increases with more frames on this reference string (no anomaly triggered here) — try the "belady" preset reference string to see it.`;
  }
}

// =========================== boot ===========================
renderCpuTabs(); renderGantt(); renderProcessTable();
renderComparisonGrid();
renderVmTabs(); setupScrub(); renderVmFrame();
renderAnomalyChart();
</script>
</body>
</html>
"""
