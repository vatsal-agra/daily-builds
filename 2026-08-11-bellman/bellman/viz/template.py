"""The report's HTML/CSS/JS shell. bellman/viz/report.py substitutes the
literal string __BELLMAN_DATA__ with real, computed JSON -- everything
this page renders (heatmaps, training curves, replayed episodes) came out
of an actual training run, nothing here is a mock.
"""

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bellman — a from-scratch reinforcement learning study</title>
<style>
  :root {
    --bg: #f4f5f7;
    --panel: #ffffff;
    --panel-border: #e1e4ea;
    --text: #1b1e27;
    --text-dim: #5b6070;
    --accent: #3457d5;
    --accent-2: #d1495b;
    --accent-3: #2a9d8f;
    --grid-empty: #eef1f6;
    --grid-wall: #4b4f5c;
    --grid-goal: #2a9d8f;
    --grid-hole: #d1495b;
    --grid-cliff: #e07a1f;
    --grid-start: #f2c14e;
    --code-bg: #eceef3;
    --shadow: 0 1px 3px rgba(20,22,30,0.08), 0 1px 2px rgba(20,22,30,0.06);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #14161c;
      --panel: #1b1e27;
      --panel-border: #2b2f3b;
      --text: #e7e9ef;
      --text-dim: #9298ab;
      --accent: #7c93ff;
      --accent-2: #ff8095;
      --accent-3: #5fd4c4;
      --grid-empty: #23262f;
      --grid-wall: #3a3d47;
      --grid-goal: #1f7a6e;
      --grid-hole: #a53347;
      --grid-cliff: #b5651d;
      --grid-start: #c99a2e;
      --code-bg: #21242e;
      --shadow: 0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3);
    }
  }
  :root[data-theme="dark"] {
    --bg: #14161c;
    --panel: #1b1e27;
    --panel-border: #2b2f3b;
    --text: #e7e9ef;
    --text-dim: #9298ab;
    --accent: #7c93ff;
    --accent-2: #ff8095;
    --accent-3: #5fd4c4;
    --grid-empty: #23262f;
    --grid-wall: #3a3d47;
    --grid-goal: #1f7a6e;
    --grid-hole: #a53347;
    --grid-cliff: #b5651d;
    --grid-start: #c99a2e;
    --code-bg: #21242e;
    --shadow: 0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  main { max-width: 1180px; margin: 0 auto; padding: 40px 24px 80px; }
  header.hero { padding: 8px 0 32px; border-bottom: 1px solid var(--panel-border); margin-bottom: 32px; }
  header.hero h1 { font-size: 30px; margin: 0 0 8px; letter-spacing: -0.02em; }
  header.hero p { color: var(--text-dim); max-width: 74ch; margin: 0; }
  h2.section-title { font-size: 21px; margin: 0 0 6px; letter-spacing: -0.01em; }
  p.section-sub { color: var(--text-dim); margin: 0 0 20px; max-width: 80ch; }
  section { margin-bottom: 56px; }
  .card {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    padding: 20px 22px;
    box-shadow: var(--shadow);
  }
  .env-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }
  .env-card h3 { margin: 0 0 2px; font-size: 16px; }
  .env-card .meta { color: var(--text-dim); font-size: 12.5px; margin-bottom: 12px; }
  .env-card canvas.grid-canvas { display: block; margin: 0 auto; border-radius: 8px; }
  .stat-row { display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }
  .stat-pill {
    background: var(--code-bg); border-radius: 8px; padding: 6px 10px; font-size: 12.5px;
    color: var(--text-dim);
  }
  .stat-pill b { color: var(--text); }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-dim); margin: 6px 0 10px; }
  .legend span.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
  .btnbar { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
  button {
    font: inherit; font-size: 12.5px; cursor: pointer; border-radius: 7px; padding: 6px 12px;
    border: 1px solid var(--panel-border); background: var(--code-bg); color: var(--text);
  }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); color: white; border-color: var(--accent); }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 820px) { .two-col { grid-template-columns: 1fr; } }
  canvas.chart-canvas { display: block; width: 100%; height: 200px; }
  canvas.pole-canvas { display: block; margin: 0 auto; border-radius: 8px; }
  code.hint { background: var(--code-bg); border-radius: 5px; padding: 1px 6px; font-size: 12px; }
  footer { color: var(--text-dim); font-size: 12.5px; padding-top: 20px; border-top: 1px solid var(--panel-border); }
</style>
</head>
<body>
<main>
  <header class="hero">
    <h1>Bellman</h1>
    <p>A from-scratch reinforcement-learning study: exact dynamic-programming
       solutions for discrete gridworld MDPs, tabular agents checked
       against that ground truth, and a continuous-state cart-pole solved
       by two structurally different function-approximation methods
       (Deep Q-Network and REINFORCE). Every number and animation on this
       page came out of a real training run in this repository, not a
       mock.</p>
  </header>

  <section id="gridworlds">
    <h2 class="section-title">Exact solutions vs. learned policies</h2>
    <p class="section-sub">Each environment's optimal value function
      V*(s) is solved exactly by value iteration (the heatmap + arrows).
      Q-learning, SARSA, and Monte-Carlo control then learn a policy from
      scratch by trial and error alone — the match stat is how many
      states their final greedy policy agrees with the DP oracle on.</p>
    <div class="env-grid" id="gridworld-cards"></div>
  </section>

  <section id="cliff">
    <h2 class="section-title">On-policy vs. off-policy: CliffWalking</h2>
    <p class="section-sub">The classic divergence (Sutton &amp; Barto,
      figure 6.13): Q-learning is off-policy and always bootstraps from
      the greedy next action, so it learns the optimal risky path right
      along the cliff edge. SARSA is on-policy and bootstraps from the
      action its own epsilon-greedy behavior will actually take next, so
      it learns a policy that stays safely away from the cliff.</p>
    <div class="card">
      <div class="legend">
        <span><span class="swatch" style="background:var(--accent-2)"></span>Q-learning (off-policy)</span>
        <span><span class="swatch" style="background:var(--accent)"></span>SARSA (on-policy)</span>
        <span><span class="swatch" style="background:var(--grid-cliff)"></span>cliff</span>
      </div>
      <canvas id="cliff-canvas" class="grid-canvas"></canvas>
    </div>
  </section>

  <section id="cartpole">
    <h2 class="section-title">Function approximation: CartPole</h2>
    <p class="section-sub">Cart-pole's four-dimensional continuous state
      has no finite table, so both agents here learn from a small neural
      network instead. DQN learns a value function and bootstraps from a
      target network over replayed transitions (off-policy, TD).
      REINFORCE learns a policy directly from full-episode Monte-Carlo
      returns with a learned baseline (on-policy, no bootstrapping).</p>
    <div class="two-col">
      <div class="card">
        <h3 style="margin-top:0">Deep Q-Network</h3>
        <div class="stat-row" id="dqn-stats"></div>
        <canvas id="dqn-chart" class="chart-canvas"></canvas>
        <canvas id="dqn-pole" class="pole-canvas" width="440" height="180"></canvas>
        <div class="btnbar">
          <button class="primary" onclick="poleControllers.dqn.play()">▶ replay episode</button>
          <button onclick="poleControllers.dqn.reset()">reset</button>
        </div>
      </div>
      <div class="card">
        <h3 style="margin-top:0">REINFORCE</h3>
        <div class="stat-row" id="reinforce-stats"></div>
        <canvas id="reinforce-chart" class="chart-canvas"></canvas>
        <canvas id="reinforce-pole" class="pole-canvas" width="440" height="180"></canvas>
        <div class="btnbar">
          <button class="primary" onclick="poleControllers.reinforce.play()">▶ replay episode</button>
          <button onclick="poleControllers.reinforce.reset()">reset</button>
        </div>
      </div>
    </div>
  </section>

  <footer>
    Generated by <code class="hint">bellman/viz/report.py</code> from a
    real run of every algorithm in this repository. No client-side RL —
    every curve, heatmap, and replay is precomputed data.
  </footer>
</main>

<script>
const DATA = __BELLMAN_DATA__;
const ACTION_ARROWS = ["↑", "→", "↓", "←"]; // UP, RIGHT, DOWN, LEFT

function cellColor(cell) {
  switch (cell.kind) {
    case "wall": return getCss("--grid-wall");
    case "goal": return getCss("--grid-goal");
    case "hole": return getCss("--grid-hole");
    case "cliff": return getCss("--grid-cliff");
    case "start": return getCss("--grid-start");
    default: return null; // heatmap-colored
  }
}

function getCss(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
}

function heatColor(v, vmin, vmax) {
  const t = vmax > vmin ? (v - vmin) / (vmax - vmin) : 0.5;
  // cool (low) -> warm (high), through the panel background so it reads
  // fine in both themes
  const r = Math.round(70 + t * 150);
  const g = Math.round(90 + t * 90);
  const b = Math.round(180 - t * 120);
  return `rgb(${r},${g},${b})`;
}

function drawGridBase(ctx, cells, rows, cols, cellSize) {
  let vmin = Infinity, vmax = -Infinity;
  for (const row of cells) for (const c of row) {
    if (c.v !== null && c.v !== undefined) { vmin = Math.min(vmin, c.v); vmax = Math.max(vmax, c.v); }
  }
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const cell = cells[r][c];
      const x = c * cellSize, y = r * cellSize;
      let color = cellColor(cell);
      if (color === null) color = heatColor(cell.v, vmin, vmax);
      ctx.fillStyle = color;
      ctx.fillRect(x, y, cellSize, cellSize);
      ctx.strokeStyle = getCss("--panel-border");
      ctx.strokeRect(x + 0.5, y + 0.5, cellSize - 1, cellSize - 1);
      if (cell.action !== null && cell.action !== undefined && cell.kind === "empty") {
        ctx.fillStyle = "rgba(255,255,255,0.92)";
        ctx.font = `${Math.floor(cellSize * 0.42)}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(ACTION_ARROWS[cell.action], x + cellSize / 2, y + cellSize / 2 + 1);
      }
    }
  }
}

function buildGridworldCard(container, key, section) {
  const card = document.createElement("div");
  card.className = "card env-card";
  const agentNames = { qlearning: "Q-learning", sarsa: "SARSA", montecarlo: "Monte Carlo" };
  card.innerHTML = `
    <h3>${section.name}</h3>
    <div class="meta">V*(start) = ${section.optimal_value_at_start} (exact, via value iteration)</div>
    <canvas class="grid-canvas" width="${section.cols * 40}" height="${section.rows * 40}"></canvas>
    <div class="stat-row">${Object.entries(section.matches).map(([k, m]) =>
      `<span class="stat-pill">${agentNames[k]}: <b>${m.matches}/${m.total}</b> states match optimal</span>`).join("")}</div>
    <canvas class="chart-canvas" height="130"></canvas>
    <div class="legend">
      <span><span class="swatch" style="background:#e07a1f"></span>Q-learning</span>
      <span><span class="swatch" style="background:#3457d5"></span>SARSA</span>
      <span><span class="swatch" style="background:#2a9d8f"></span>Monte Carlo</span>
    </div>
    <div class="btnbar">
      ${Object.keys(agentNames).map(k => `<button data-agent="${k}">▶ replay ${agentNames[k]}</button>`).join("")}
    </div>
  `;
  container.appendChild(card);

  const gridCanvas = card.querySelector(".grid-canvas");
  const gctx = gridCanvas.getContext("2d");
  const cellSize = 40;
  drawGridBase(gctx, section.cells, section.rows, section.cols, cellSize);

  const chartCanvas = card.querySelector(".chart-canvas");
  drawLineChart(chartCanvas, [
    { name: "Q-learning", color: "#e07a1f", values: section.curves.qlearning },
    { name: "SARSA", color: "#3457d5", values: section.curves.sarsa },
    { name: "Monte Carlo", color: "#2a9d8f", values: section.curves.montecarlo },
  ], "episode reward (smoothed)");

  card.querySelectorAll("button[data-agent]").forEach(btn => {
    btn.addEventListener("click", () => {
      const path = section.final_paths[btn.dataset.agent];
      animatePath(gctx, section.cells, section.rows, section.cols, cellSize, path);
    });
  });
}

function animatePath(ctx, cells, rows, cols, cellSize, path) {
  let i = 0;
  function step() {
    drawGridBase(ctx, cells, rows, cols, cellSize);
    for (let j = 0; j <= i && j < path.length; j++) {
      const [r, c] = path[j];
      ctx.fillStyle = "rgba(52,87,213,0.35)";
      ctx.beginPath();
      ctx.arc(c * cellSize + cellSize / 2, r * cellSize + cellSize / 2, cellSize * 0.14, 0, 2 * Math.PI);
      ctx.fill();
    }
    const [r, c] = path[Math.min(i, path.length - 1)];
    ctx.fillStyle = "#d1495b";
    ctx.beginPath();
    ctx.arc(c * cellSize + cellSize / 2, r * cellSize + cellSize / 2, cellSize * 0.22, 0, 2 * Math.PI);
    ctx.fill();
    i++;
    if (i < path.length) setTimeout(step, 140);
  }
  step();
}

function drawLineChart(canvas, series, yLabel) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth || canvas.width || 400;
  const cssHeight = canvas.height || 200;
  canvas.width = cssWidth * dpr;
  canvas.height = cssHeight * dpr;
  canvas.style.width = cssWidth + "px";
  canvas.style.height = cssHeight + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const allValues = series.flatMap(s => s.values).filter(v => v !== null && v !== undefined);
  if (allValues.length === 0) return;
  const vmin = Math.min(...allValues), vmax = Math.max(...allValues);
  const pad = 28;
  const plotW = cssWidth - pad * 1.4, plotH = cssHeight - pad * 1.6;

  ctx.strokeStyle = getCss("--panel-border");
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, 10);
  ctx.lineTo(pad, plotH + 10);
  ctx.lineTo(pad + plotW, plotH + 10);
  ctx.stroke();

  ctx.fillStyle = getCss("--text-dim");
  ctx.font = "10.5px sans-serif";
  ctx.fillText(vmax.toFixed(0), 2, 16);
  ctx.fillText(vmin.toFixed(0), 2, plotH + 12);

  for (const s of series) {
    const values = s.values;
    if (!values || values.length === 0) continue;
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    values.forEach((v, idx) => {
      if (v === null || v === undefined) return;
      const x = pad + (idx / Math.max(1, values.length - 1)) * plotW;
      const y = 10 + plotH - ((v - vmin) / Math.max(1e-9, vmax - vmin)) * plotH;
      if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
}

// --- cart-pole replay -----------------------------------------------
function makePoleController(canvasId, replay) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const trackY = H * 0.72;
  const pxPerUnit = W / 6.0; // +-2.4 track half-width with margin
  let frame = 0, timer = null;

  function drawFrame(i) {
    const [x, theta] = replay[Math.min(i, replay.length - 1)];
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = getCss("--panel-border");
    ctx.beginPath(); ctx.moveTo(0, trackY); ctx.lineTo(W, trackY); ctx.stroke();

    const cx = W / 2 + x * pxPerUnit;
    const cartW = 46, cartH = 26;
    ctx.fillStyle = getCss("--accent");
    ctx.fillRect(cx - cartW / 2, trackY - cartH / 2, cartW, cartH);

    const poleLen = 70;
    const tipX = cx + Math.sin(theta) * poleLen;
    const tipY = trackY - cartH / 2 - Math.cos(theta) * poleLen;
    ctx.strokeStyle = getCss("--accent-2");
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(cx, trackY - cartH / 2); ctx.lineTo(tipX, tipY); ctx.stroke();
    ctx.fillStyle = getCss("--accent-2");
    ctx.beginPath(); ctx.arc(tipX, tipY, 5, 0, 2 * Math.PI); ctx.fill();

    ctx.fillStyle = getCss("--text-dim");
    ctx.font = "11px sans-serif";
    ctx.fillText(`step ${i}/${replay.length - 1}`, 8, 14);
  }

  drawFrame(0);

  return {
    play() {
      if (timer) clearInterval(timer);
      frame = 0;
      timer = setInterval(() => {
        drawFrame(frame);
        frame++;
        if (frame >= replay.length) { clearInterval(timer); timer = null; }
      }, 20);
    },
    reset() {
      if (timer) clearInterval(timer);
      timer = null; frame = 0; drawFrame(0);
    },
  };
}

// --- assemble the page -------------------------------------------------
const gwContainer = document.getElementById("gridworld-cards");
for (const [key, section] of Object.entries(DATA.gridworlds)) {
  buildGridworldCard(gwContainer, key, section);
}

(function renderCliff() {
  const c = DATA.cliff_compare;
  const cellSize = 46;
  const canvas = document.getElementById("cliff-canvas");
  canvas.width = c.cols * cellSize;
  canvas.height = c.rows * cellSize;
  const ctx = canvas.getContext("2d");
  const cliffSet = new Set(c.cliffs.map(([r, cc]) => `${r},${cc}`));

  function drawBase() {
    for (let r = 0; r < c.rows; r++) {
      for (let cc = 0; cc < c.cols; cc++) {
        const x = cc * cellSize, y = r * cellSize;
        ctx.fillStyle = cliffSet.has(`${r},${cc}`) ? getCss("--grid-cliff") : getCss("--grid-empty");
        ctx.fillRect(x, y, cellSize, cellSize);
        ctx.strokeStyle = getCss("--panel-border");
        ctx.strokeRect(x + 0.5, y + 0.5, cellSize - 1, cellSize - 1);
      }
    }
    ctx.fillStyle = getCss("--grid-start");
    ctx.fillRect(c.start[1] * cellSize + 4, c.start[0] * cellSize + 4, cellSize - 8, cellSize - 8);
    ctx.fillStyle = getCss("--grid-goal");
    ctx.fillRect(c.goal[1] * cellSize + 4, c.goal[0] * cellSize + 4, cellSize - 8, cellSize - 8);
  }

  function drawPath(path, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    path.forEach(([r, cc], i) => {
      const x = cc * cellSize + cellSize / 2, y = r * cellSize + cellSize / 2;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  drawBase();
  drawPath(c.qlearning_path, "#d1495b");
  drawPath(c.sarsa_path, "#3457d5");
})();

function statPills(container, evalStats) {
  container.innerHTML = `
    <span class="stat-pill">eval mean: <b>${evalStats.eval_mean}</b></span>
    <span class="stat-pill">min: <b>${evalStats.eval_min}</b></span>
    <span class="stat-pill">max: <b>${evalStats.eval_max}</b></span>
  `;
}
statPills(document.getElementById("dqn-stats"), DATA.cartpole.dqn);
statPills(document.getElementById("reinforce-stats"), DATA.cartpole.reinforce);

drawLineChart(document.getElementById("dqn-chart"),
  [{ name: "DQN", color: "#3457d5", values: DATA.cartpole.dqn.reward_curve }], "reward");
drawLineChart(document.getElementById("reinforce-chart"),
  [{ name: "REINFORCE", color: "#2a9d8f", values: DATA.cartpole.reinforce.reward_curve }], "reward");

const poleControllers = {
  dqn: makePoleController("dqn-pole", DATA.cartpole.dqn.replay),
  reinforce: makePoleController("reinforce-pole", DATA.cartpole.reinforce.replay),
};
</script>
</body>
</html>
"""
