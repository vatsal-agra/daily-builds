"""Renders results/*.json into a single self-contained interactive HTML
report: learning curves, a live-replayed GridWorld policy heatmap, the
Cliff Walking path divergence drawn on the grid, canvas replays of trained
CartPole episodes (real recorded physics frames), and the DQN ablation
comparison. No CDN, no build step, no server — every chart is plain
inline SVG/Canvas/JS reading the JSON this script embeds directly into
the page.
"""

from __future__ import annotations

import argparse
import json
import os

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "report.html")

ACTION_ARROWS = ["↑", "→", "↓", "←"]  # up, right, down, left


def _load(name):
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def build_report(out_path=DEFAULT_OUT):
    data = {
        "qlearning": _load("qlearning_simplegrid"),
        "sarsa": _load("sarsa_simplegrid"),
        "cliff": _load("cliff_compare"),
        "dqn": _load("dqn_cartpole"),
        "reinforce": _load("reinforce_cartpole"),
        "ablation": _load("dqn_ablation_summary"),
    }
    missing = [k for k, v in data.items() if v is None]
    if missing:
        raise SystemExit(
            f"missing results for: {missing} — run `python -m bellman.train demo` "
            "(or the individual commands) first"
        )
    payload = json.dumps(data)
    html = _TEMPLATE.replace("__BELLMAN_DATA__", payload)
    with open(out_path, "w") as f:
        f.write(html)
    print(f"wrote {out_path} ({os.path.getsize(out_path) / 1024:.0f} KB)")
    return out_path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bellman — Reinforcement Learning From Scratch</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0f1420; --panel: #161d2e; --panel2: #1d2740; --text: #e7ecf7;
    --muted: #93a0bd; --accent: #6ea8fe; --accent2: #ffb454; --good: #37d67a;
    --bad: #ff6b6b; --grid-line: #2a3552; --wall: #3a4262; --cliff: #7a2033;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 0 0 4rem;
  }
  header {
    padding: 3rem 2rem 1.5rem; text-align: center;
    background: radial-gradient(ellipse at top, #1a2744 0%, var(--bg) 70%);
    border-bottom: 1px solid var(--grid-line);
  }
  header h1 { margin: 0 0 .3rem; font-size: 2.4rem; letter-spacing: -0.02em; }
  header p { margin: 0; color: var(--muted); font-size: 1.05rem; }
  nav { display: flex; justify-content: center; gap: .5rem; flex-wrap: wrap; margin-top: 1.5rem; }
  nav a {
    color: var(--text); text-decoration: none; padding: .4rem .9rem;
    border: 1px solid var(--grid-line); border-radius: 999px; font-size: .85rem;
  }
  nav a:hover { border-color: var(--accent); color: var(--accent); }
  main { max-width: 1100px; margin: 0 auto; padding: 0 1.5rem; }
  section { margin-top: 3.5rem; scroll-margin-top: 1rem; }
  section h2 { font-size: 1.5rem; margin-bottom: .2rem; }
  section .subtitle { color: var(--muted); margin-bottom: 1.2rem; max-width: 70ch; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; }
  @media (max-width: 800px) { .grid2 { grid-template-columns: 1fr; } }
  .panel {
    background: var(--panel); border: 1px solid var(--grid-line); border-radius: 12px;
    padding: 1.2rem 1.3rem;
  }
  .panel h3 { margin: 0 0 .8rem; font-size: 1rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
  .stat-row { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: .6rem 0 1rem; }
  .stat { background: var(--panel2); border-radius: 8px; padding: .6rem 1rem; min-width: 120px; }
  .stat .v { font-size: 1.4rem; font-weight: 700; }
  .stat .l { color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .03em; }
  .ok { color: var(--good); } .bad { color: var(--bad); }
  svg text { fill: var(--muted); font-size: 10px; }
  .curve-legend { display: flex; gap: 1.2rem; font-size: .82rem; color: var(--muted); margin-top: .4rem; flex-wrap: wrap; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: .35rem; vertical-align: middle; }
  .controls { display: flex; align-items: center; gap: .8rem; margin-top: .8rem; flex-wrap: wrap; }
  button {
    background: var(--panel2); color: var(--text); border: 1px solid var(--grid-line);
    border-radius: 8px; padding: .5rem 1rem; cursor: pointer; font-size: .85rem;
  }
  button:hover { border-color: var(--accent); }
  .grid-cell-goal { fill: #21402c; } .grid-cell-wall { fill: var(--wall); }
  .grid-cell-cliff { fill: var(--cliff); }
  footer { text-align: center; color: var(--muted); margin-top: 4rem; font-size: .85rem; }
  code { background: var(--panel2); padding: .1rem .4rem; border-radius: 4px; font-size: .85em; }
</style>
</head>
<body>
<header>
  <h1>Bellman</h1>
  <p>A reinforcement learning toolkit built entirely from scratch — tabular Q-learning &amp; SARSA, a Deep Q-Network, and REINFORCE.</p>
  <nav>
    <a href="#gridworld">GridWorld</a>
    <a href="#cliff">Cliff Walking</a>
    <a href="#dqn">DQN</a>
    <a href="#reinforce">REINFORCE</a>
    <a href="#ablation">DQN Ablation</a>
  </nav>
</header>
<main>

<section id="gridworld">
  <h2>Tabular Q-learning &amp; SARSA vs. exact value iteration</h2>
  <p class="subtitle">Both agents train on the same 5x5 GridWorld by trial and error alone. Their learned greedy policies
  are checked against an exact dynamic-programming solve of the same MDP — a policy is "correct" if rolling it out from
  the start achieves the true optimal discounted return, not just "reward went up".</p>
  <div class="grid2">
    <div class="panel">
      <h3>Q-learning — learned policy</h3>
      <div id="grid-qlearning"></div>
      <div class="stat-row" id="stats-qlearning"></div>
    </div>
    <div class="panel">
      <h3>SARSA — learned policy</h3>
      <div id="grid-sarsa"></div>
      <div class="stat-row" id="stats-sarsa"></div>
    </div>
  </div>
  <div class="panel" style="margin-top:1.2rem">
    <h3>Learning curves</h3>
    <div id="curve-gridworld"></div>
    <div class="curve-legend">
      <span><span class="swatch" style="background:var(--accent)"></span>Q-learning (moving avg)</span>
      <span><span class="swatch" style="background:var(--accent2)"></span>SARSA (moving avg)</span>
    </div>
  </div>
</section>

<section id="cliff">
  <h2>Cliff Walking: the classic on-policy/off-policy divergence</h2>
  <p class="subtitle">Sutton &amp; Barto's Example 6.6: off-policy Q-learning converges to the optimal-but-risky path
  hugging the cliff edge; on-policy SARSA, whose updates account for its own exploratory epsilon-greedy policy occasionally
  stepping into the cliff, converges to a longer but safer route. Same environment, same hyperparameters, only the
  update rule differs.</p>
  <div class="panel">
    <div id="grid-cliff"></div>
    <div class="curve-legend">
      <span><span class="swatch" style="background:var(--accent)"></span>Q-learning path (risky)</span>
      <span><span class="swatch" style="background:var(--accent2)"></span>SARSA path (safe)</span>
    </div>
    <div class="stat-row" id="stats-cliff"></div>
  </div>
</section>

<section id="dqn">
  <h2>Deep Q-Network on CartPole</h2>
  <p class="subtitle">A hand-rolled MLP Q-function trained with experience replay and a periodically-synced target network.
  Reward is +1 per timestep alive; the episode ends when the pole falls past +-12&deg; or the cart leaves the track.</p>
  <div class="grid2">
    <div class="panel">
      <h3>Training curve</h3>
      <div id="curve-dqn"></div>
      <div class="stat-row" id="stats-dqn"></div>
    </div>
    <div class="panel">
      <h3>Replay: a real evaluation episode</h3>
      <canvas id="replay-dqn" width="440" height="240"></canvas>
      <div class="controls">
        <button onclick="playReplay('dqn')">Play</button>
        <span id="replay-dqn-info" style="color:var(--muted); font-size:.85rem"></span>
      </div>
    </div>
  </div>
</section>

<section id="reinforce">
  <h2>REINFORCE on CartPole</h2>
  <p class="subtitle">Monte Carlo policy gradient with a learned value baseline — a full episode is played out, then the
  log-probability of every action taken is nudged up or down in proportion to how much better the actual discounted
  return was than the baseline's prediction for that state.</p>
  <div class="grid2">
    <div class="panel">
      <h3>Training curve</h3>
      <div id="curve-reinforce"></div>
      <div class="stat-row" id="stats-reinforce"></div>
    </div>
    <div class="panel">
      <h3>Replay: a real evaluation episode</h3>
      <canvas id="replay-reinforce" width="440" height="240"></canvas>
      <div class="controls">
        <button onclick="playReplay('reinforce')">Play</button>
        <span id="replay-reinforce-info" style="color:var(--muted); font-size:.85rem"></span>
      </div>
    </div>
  </div>
</section>

<section id="ablation">
  <h2>DQN ablation: why the two tricks matter</h2>
  <p class="subtitle">The same DQN, with experience replay and/or the target network disabled, averaged over several
  training seeds each (a single run is too noisy to honestly credit to the ablated component). <strong>Max drawdown</strong>
  is the largest drop from any earlier peak of the training moving-average return — it catches "learned fine, then
  collapsed", the specific failure mode these two tricks exist to prevent, even on a run whose final number happens to
  land fine anyway.</p>
  <div class="panel">
    <h3>Training curves (one representative seed per variant)</h3>
    <div id="curve-ablation"></div>
    <div class="curve-legend" id="ablation-legend"></div>
  </div>
  <div class="panel" style="margin-top:1.2rem">
    <h3>Summary across seeds</h3>
    <div id="ablation-table"></div>
  </div>
</section>

</main>
<footer>Bellman — every agent, environment, and neural net in this report was trained from scratch, from these exact JSON logs.</footer>

<script>
const DATA = __BELLMAN_DATA__;
const NS = "http://www.w3.org/2000/svg";
function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
function statBlock(container, entries) {
  container.innerHTML = "";
  for (const [label, value, cls] of entries) {
    const d = document.createElement("div");
    d.className = "stat";
    d.innerHTML = `<div class="v ${cls||''}">${value}</div><div class="l">${label}</div>`;
    container.appendChild(d);
  }
}

// ---- line chart (raw + moving average, arbitrary number of series) ----
function lineChart(containerId, series, opts) {
  opts = opts || {};
  const w = opts.width || 520, h = opts.height || 220, pad = 34;
  const el0 = document.getElementById(containerId);
  const svg = el("svg", {width: w, height: h, viewBox: `0 0 ${w} ${h}`}, null);
  el0.appendChild(svg);
  const allY = series.flatMap(s => s.values);
  const n = Math.max(...series.map(s => s.values.length), 2);
  const yMin = Math.min(...allY), yMax = Math.max(...allY);
  const yPad = (yMax - yMin) * 0.08 || 1;
  const xScale = i => pad + (i / (n - 1)) * (w - pad - 12);
  const yScale = v => h - pad + 6 - ((v - (yMin - yPad)) / ((yMax + yPad) - (yMin - yPad))) * (h - pad - 20);
  // gridlines
  for (let i = 0; i <= 4; i++) {
    const y = pad - 14 + i * (h - pad - 20) / 4;
    el("line", {x1: pad, x2: w - 8, y1: y, y2: y, stroke: "#2a3552", "stroke-width": 1}, svg);
  }
  el("line", {x1: pad, x2: pad, y1: 10, y2: h - pad + 6, stroke: "#3a4262"}, svg);
  el("line", {x1: pad, x2: w - 8, y1: h - pad + 6, y2: h - pad + 6, stroke: "#3a4262"}, svg);
  el("text", {x: 4, y: yScale(yMax) + 4}, svg).textContent = yMax.toFixed(0);
  el("text", {x: 4, y: yScale(yMin) + 4}, svg).textContent = yMin.toFixed(0);
  el("text", {x: pad, y: h - 6}, svg).textContent = "0";
  el("text", {x: w - 30, y: h - 6}, svg).textContent = n + " ep";
  for (const s of series) {
    const pts = s.values.map((v, i) => `${xScale(i)},${yScale(v)}`).join(" ");
    el("polyline", {points: pts, fill: "none", stroke: s.color, "stroke-width": s.width || 2, opacity: s.opacity || 1}, svg);
  }
  return svg;
}

// ---- gridworld drawing (walls, cliffs, goal, start, optional policy arrows) ----
function drawGrid(containerId, layout, opts) {
  opts = opts || {};
  const cell = opts.cell || 34;
  const w = layout.width * cell, h = layout.height * cell;
  const container = document.getElementById(containerId);
  const svg = el("svg", {width: w, height: h, viewBox: `0 0 ${w} ${h}`}, null);
  container.appendChild(svg);
  const wallSet = new Set(layout.walls.map(([r,c]) => r + "," + c));
  const cliffSet = new Set((layout.cliffs||[]).map(([r,c]) => r + "," + c));
  for (let r = 0; r < layout.height; r++) {
    for (let c = 0; c < layout.width; c++) {
      let cls = "";
      if (wallSet.has(r+","+c)) cls = "grid-cell-wall";
      else if (cliffSet.has(r+","+c)) cls = "grid-cell-cliff";
      else if (r === layout.goal[0] && c === layout.goal[1]) cls = "grid-cell-goal";
      el("rect", {x: c*cell, y: r*cell, width: cell, height: cell, class: cls, fill: cls?undefined:"#111726",
                  stroke: "#232d47"}, svg);
    }
  }
  // start marker
  const [sr, sc] = layout.start;
  el("circle", {cx: sc*cell+cell/2, cy: sr*cell+cell/2, r: cell*0.14, fill: "#6ea8fe"}, svg);
  // goal marker
  const [gr, gc] = layout.goal;
  el("text", {x: gc*cell+cell/2, y: gr*cell+cell/2+5, "text-anchor": "middle", fill:"#37d67a", "font-size": cell*0.5}, svg).textContent = "⚑";
  return svg;
}

function drawPolicyArrows(svg, layout, policy, cell) {
  cell = cell || 34;
  const ARROWS = ["↑","→","↓","←"];
  const wallSet = new Set(layout.walls.map(([r,c]) => r + "," + c));
  for (let r = 0; r < layout.height; r++) {
    for (let c = 0; c < layout.width; c++) {
      if (wallSet.has(r+","+c)) continue;
      if (r === layout.goal[0] && c === layout.goal[1]) continue;
      const s = r * layout.width + c;
      const a = policy[s];
      el("text", {x: c*cell+cell/2, y: r*cell+cell/2+5, "text-anchor":"middle", fill:"#93a0bd", "font-size": cell*0.42}, svg).textContent = ARROWS[a];
    }
  }
}

function drawPath(svg, layout, path, color, cell, dashOffset) {
  cell = cell || 34;
  const pts = path.map(([r,c]) => `${c*cell+cell/2},${r*cell+cell/2}`).join(" ");
  el("polyline", {points: pts, fill: "none", stroke: color, "stroke-width": 3.5, opacity: 0.85,
                   "stroke-dasharray": dashOffset ? "6,4" : undefined}, svg);
}

// ================= GridWorld section =================
(function() {
  const ql = DATA.qlearning, sa = DATA.sarsa;
  const svgQ = drawGrid("grid-qlearning", ql.layout);
  drawPolicyArrows(svgQ, ql.layout, ql.policy);
  const svgS = drawGrid("grid-sarsa", sa.layout);
  drawPolicyArrows(svgS, sa.layout, sa.policy);

  statBlock(document.getElementById("stats-qlearning"), [
    ["Optimal rollout", ql.optimal_rollout ? "YES" : "NO", ql.optimal_rollout ? "ok" : "bad"],
    ["Episodes", ql.episodes],
    ["Value-close states", `${ql.value_close}/${ql.total_states}`],
  ]);
  statBlock(document.getElementById("stats-sarsa"), [
    ["Optimal rollout", sa.optimal_rollout ? "YES" : "NO", sa.optimal_rollout ? "ok" : "bad"],
    ["Episodes", sa.episodes],
    ["Value-close states", `${sa.value_close}/${sa.total_states}`],
  ]);

  lineChart("curve-gridworld", [
    {values: ql.moving_avg, color: "#6ea8fe"},
    {values: sa.moving_avg, color: "#ffb454"},
  ]);
})();

// ================= Cliff Walking section =================
(function() {
  const c = DATA.cliff;
  const svg = drawGrid("grid-cliff", c.layout, {cell: 30});
  drawPath(svg, c.layout, c.qlearning.path, "#6ea8fe", 30, false);
  drawPath(svg, c.layout, c.sarsa.path, "#ffb454", 30, true);
  statBlock(document.getElementById("stats-cliff"), [
    ["Divergence reproduced", c.diverged ? "YES" : "NO", c.diverged ? "ok" : "bad"],
    ["Q-learning path length", c.qlearning.path.length],
    ["SARSA path length", c.sarsa.path.length],
    ["Q-learning edge-row %", (c.qlearning.edge_fraction*100).toFixed(0)+"%"],
    ["SARSA edge-row %", (c.sarsa.edge_fraction*100).toFixed(0)+"%"],
  ]);
})();

// ================= DQN / REINFORCE sections =================
function cartpoleSection(key, obj) {
  lineChart("curve-" + key, [
    {values: obj.returns, color: "#3a4262", width: 1, opacity: 0.6},
    {values: obj.moving_avg, color: "#6ea8fe", width: 2.2},
  ]);
  statBlock(document.getElementById("stats-" + key), [
    ["Eval avg return", obj.eval_avg.toFixed(0)],
    ["Episodes trained", obj.episodes],
    ["Train time", obj.elapsed_sec.toFixed(1) + "s"],
  ]);
}
cartpoleSection("dqn", DATA.dqn);
cartpoleSection("reinforce", DATA.reinforce);

// ---- CartPole canvas replay ----
const replayTimers = {};
function drawCartpole(ctx, w, h, x, theta) {
  ctx.fillStyle = "#0f1420"; ctx.fillRect(0, 0, w, h);
  const scale = w / 6; // +-2.4 track half-width plus margin fits in view
  const groundY = h * 0.75;
  ctx.strokeStyle = "#3a4262"; ctx.beginPath(); ctx.moveTo(0, groundY); ctx.lineTo(w, groundY); ctx.stroke();
  const cx = w/2 + x*scale;
  const cartW = 60, cartH = 30;
  ctx.fillStyle = "#6ea8fe";
  ctx.fillRect(cx - cartW/2, groundY - cartH, cartW, cartH);
  const poleLen = 100;
  const px = cx + Math.sin(theta) * poleLen;
  const py = (groundY - cartH) - Math.cos(theta) * poleLen;
  ctx.strokeStyle = "#ffb454"; ctx.lineWidth = 6;
  ctx.beginPath(); ctx.moveTo(cx, groundY - cartH); ctx.lineTo(px, py); ctx.stroke();
  ctx.lineWidth = 1;
  ctx.fillStyle = "#37d67a";
  ctx.beginPath(); ctx.arc(cx, groundY - cartH, 5, 0, 7); ctx.fill();
}
function playReplay(key) {
  const canvas = document.getElementById("replay-" + key);
  const ctx = canvas.getContext("2d");
  const states = DATA[key].replay;
  const info = document.getElementById("replay-" + key + "-info");
  if (replayTimers[key]) clearInterval(replayTimers[key]);
  let i = 0;
  replayTimers[key] = setInterval(() => {
    if (i >= states.length) { clearInterval(replayTimers[key]); return; }
    const [x, xdot, theta, thetadot] = states[i];
    drawCartpole(ctx, canvas.width, canvas.height, x, theta);
    info.textContent = `step ${i+1}/${states.length}`;
    i++;
  }, 20);
}
(function initReplays() {
  for (const key of ["dqn", "reinforce"]) {
    const canvas = document.getElementById("replay-" + key);
    const ctx = canvas.getContext("2d");
    const s0 = DATA[key].replay[0];
    drawCartpole(ctx, canvas.width, canvas.height, s0[0], s0[2]);
    document.getElementById("replay-" + key + "-info").textContent =
      `${DATA[key].replay.length} recorded steps`;
  }
})();

// ================= Ablation section =================
(function() {
  const ab = DATA.ablation;
  const colors = {full: "#37d67a", no_replay: "#ffb454", no_target: "#ff6b6b"};
  const labels = {full: "Full DQN", no_replay: "No replay buffer", no_target: "No target network"};
  const series = Object.keys(ab.variants).map(k => ({
    values: ab.variants[k].example_moving_avg, color: colors[k], width: 2,
  }));
  lineChart("curve-ablation", series);
  const legend = document.getElementById("ablation-legend");
  legend.innerHTML = Object.keys(ab.variants).map(k =>
    `<span><span class="swatch" style="background:${colors[k]}"></span>${labels[k]}</span>`
  ).join("");

  const table = document.getElementById("ablation-table");
  let rows = `<div style="overflow-x:auto"><table style="width:100%; border-collapse:collapse; font-size:.9rem">
    <tr style="color:var(--muted); text-align:left">
      <th style="padding:.4rem .6rem">Variant</th><th>Eval avg return</th><th>Max drawdown</th><th>Seeds</th>
    </tr>`;
  for (const k of Object.keys(ab.variants)) {
    const d = ab.variants[k];
    rows += `<tr style="border-top:1px solid var(--grid-line)">
      <td style="padding:.4rem .6rem"><span class="swatch" style="background:${colors[k]}"></span>${labels[k]}</td>
      <td>${d.eval_avg_mean.toFixed(1)} &plusmn; ${d.eval_avg_std.toFixed(1)}</td>
      <td>${d.max_drawdown_mean.toFixed(1)} &plusmn; ${d.max_drawdown_std.toFixed(1)}</td>
      <td>${d.seeds.join(", ")}</td>
    </tr>`;
  }
  rows += "</table></div>";
  table.innerHTML = rows;
})();
</script>
</body>
</html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    build_report(args.out)


if __name__ == "__main__":
    main()
