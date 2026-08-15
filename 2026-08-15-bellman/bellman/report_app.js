"use strict";
const DATA = JSON.parse(document.getElementById("bellman-data").textContent);

/* ---------------------------------------------------------------------- */
/* Tabs                                                                    */
/* ---------------------------------------------------------------------- */
document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.toggle("active", b === btn));
  document.querySelectorAll("section.tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + btn.dataset.tab));
});

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const c of children || []) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return node;
}
function movingAverage(arr, window) {
  const out = [];
  let sum = 0;
  const q = [];
  for (let i = 0; i < arr.length; i++) {
    q.push(arr[i]);
    sum += arr[i];
    if (q.length > window) sum -= q.shift();
    out.push(sum / q.length);
  }
  return out;
}

/* ---------------------------------------------------------------------- */
/* Line chart: shared canvas renderer for reward curves.                  */
/* series: [{label, color, data: number[], dashed?: bool}]                */
/* ---------------------------------------------------------------------- */
function drawLineChart(container, series, opts) {
  opts = opts || {};
  const wrap = el("div", { class: "chart-wrap" }, []);
  const canvas = el("canvas", { width: "980", height: "260" }, []);
  const tooltip = el("div", { class: "tooltip" }, []);
  wrap.appendChild(canvas);
  wrap.appendChild(tooltip);
  container.appendChild(wrap);

  const dpr = window.devicePixelRatio || 1;
  const cssW = 980, cssH = 260;
  canvas.style.width = "100%";
  canvas.style.height = cssH + "px";
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const padL = 46, padR = 14, padT = 14, padB = 28;
  const plotW = cssW - padL - padR, plotH = cssH - padT - padB;

  const n = Math.max(...series.map((s) => s.data.length));
  let yMin = Math.min(...series.flatMap((s) => s.data));
  let yMax = Math.max(...series.flatMap((s) => s.data));
  if (opts.yMin !== undefined) yMin = Math.min(yMin, opts.yMin);
  if (opts.yMax !== undefined) yMax = Math.max(yMax, opts.yMax);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const pad = (yMax - yMin) * 0.08;
  yMin -= pad; yMax += pad;

  function xAt(i) { return padL + (n <= 1 ? 0 : (i / (n - 1)) * plotW); }
  function yAt(v) { return padT + (1 - (v - yMin) / (yMax - yMin)) * plotH; }

  function render(hoverIdx) {
    ctx.clearRect(0, 0, cssW, cssH);

    // gridlines + y ticks
    ctx.strokeStyle = cssVar("--gridline");
    ctx.fillStyle = cssVar("--text-muted");
    ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const ticks = 4;
    for (let t = 0; t <= ticks; t++) {
      const v = yMin + (t / ticks) * (yMax - yMin);
      const y = yAt(v);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillText(Math.round(v).toString(), padL - 8, y);
    }

    // baseline reference line (e.g. random-policy baseline)
    if (opts.refLine !== undefined) {
      ctx.strokeStyle = cssVar("--text-muted");
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.5;
      const y = yAt(opts.refLine);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // x axis
    ctx.strokeStyle = cssVar("--baseline");
    ctx.beginPath();
    ctx.moveTo(padL, padT + plotH);
    ctx.lineTo(padL + plotW, padT + plotH);
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = cssVar("--text-muted");
    ctx.fillText(opts.xLabel || "episode", padL + plotW / 2, padT + plotH + 10);

    // series lines
    for (const s of series) {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2;
      if (s.dashed) ctx.setLineDash([5, 4]); else ctx.setLineDash([]);
      ctx.beginPath();
      s.data.forEach((v, i) => {
        const x = xAt(i), y = yAt(v);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // hover crosshair + tooltip
    if (hoverIdx !== null && hoverIdx !== undefined) {
      const x = xAt(hoverIdx);
      ctx.strokeStyle = cssVar("--text-muted");
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + plotH);
      ctx.stroke();
      for (const s of series) {
        if (s.data[hoverIdx] === undefined) continue;
        const y = yAt(s.data[hoverIdx]);
        ctx.fillStyle = s.color;
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
      }
      tooltip.style.opacity = "1";
      tooltip.style.left = x + "px";
      tooltip.style.top = padT + "px";
      tooltip.innerHTML = `<b>${opts.xLabel || "episode"} ${hoverIdx}</b><br>` +
        series.map((s) => `${s.label}: ${s.data[hoverIdx] !== undefined ? s.data[hoverIdx].toFixed(1) : "-"}`).join("<br>");
    } else {
      tooltip.style.opacity = "0";
    }
  }

  canvas.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const scale = cssW / rect.width;
    const frac = (mx * scale - padL) / plotW;
    const idx = Math.round(Math.max(0, Math.min(1, frac)) * (n - 1));
    render(idx);
  });
  canvas.addEventListener("mouseleave", () => render(null));

  render(null);

  // legend
  if (opts.legend !== false && series.length > 0) {
    const legend = el("div", { class: "legend" }, []);
    for (const s of series) {
      legend.appendChild(el("div", { class: "item" }, [
        el("div", { class: "line", style: `background:${s.color}` }, []),
        s.label,
      ]));
    }
    if (opts.refLine !== undefined) {
      legend.appendChild(el("div", { class: "item" }, [
        el("div", { class: "line", style: `background:${cssVar("--text-muted")}; border-top:2px dashed ${cssVar("--text-muted")}; background:none` }, []),
        opts.refLabel || "reference",
      ]));
    }
    container.insertBefore(legend, wrap);
  }
}

/* ---------------------------------------------------------------------- */
/* GridWorld tab                                                          */
/* ---------------------------------------------------------------------- */
function fmt(n, d) { return (Math.round(n * Math.pow(10, d || 0)) / Math.pow(10, d || 0)).toString(); }

function renderGridworld() {
  const gw = DATA.gridworld;
  const root = document.getElementById("tab-gridworld");

  const stats = el("div", { class: "stat-row" }, [
    statTile("DP-optimal return", fmt(gw.optimal_return), "Value Iteration, ground truth"),
    statTile("Q-Learning greedy return", fmt(gw.q_learning.greedy_return),
      gw.q_learning.greedy_return === gw.optimal_return ? "matches optimal exactly" : "",
      gw.q_learning.greedy_return === gw.optimal_return),
    statTile("SARSA greedy return", fmt(gw.sarsa.greedy_return), "on-policy: prefers the safer path"),
    statTile("SARSA(λ) greedy return", fmt(gw.sarsa_lambda.greedy_return), "eligibility traces"),
  ]);
  root.appendChild(stats);

  const card1 = el("div", { class: "card" }, [
    el("h2", {}, ["Learning curves"]),
    el("p", { class: "sub" }, [
      "Episode reward (20-episode moving average) for each TD-control algorithm on Cliff Walking " +
      "(" + gw.rows + "×" + gw.cols + ", slip probability " + gw.slip_prob + "). The dashed line is the " +
      "DP-computed optimal episode return — the ceiling every algorithm is trying to reach.",
    ]),
  ]);
  root.appendChild(card1);
  drawLineChart(card1, [
    { label: "Q-Learning", color: cssVar("--series-1"), data: movingAverage(gw.q_learning.rewards, 20) },
    { label: "SARSA", color: cssVar("--series-2"), data: movingAverage(gw.sarsa.rewards, 20) },
    { label: "SARSA(λ)", color: cssVar("--series-3"), data: movingAverage(gw.sarsa_lambda.rewards, 20) },
  ], { refLine: gw.optimal_return, refLabel: "DP-optimal return", xLabel: "episode" });

  const card2 = el("div", { class: "card" }, [
    el("h2", {}, ["Policy & value heatmap"]),
    el("p", { class: "sub" }, [
      "Cell color is the learned state value V(s) = maxₐ Q(s,a) (light = low, dark blue = high, matching the " +
      "DP value scale); arrows show the greedy action. Scrub through Q-Learning's training checkpoints, or " +
      "overlay the DP-optimal policy for comparison.",
    ]),
  ]);
  root.appendChild(card2);

  const gridWrap = el("div", { class: "chart-wrap" }, []);
  const cell = 40;
  const canvas = el("canvas", { width: String(gw.cols * cell), height: String(gw.rows * cell) }, []);
  canvas.style.width = "100%";
  canvas.style.maxWidth = (gw.cols * cell) + "px";
  canvas.style.height = "auto";
  gridWrap.appendChild(canvas);
  card2.appendChild(gridWrap);

  const legend = el("div", { class: "legend" }, [
    legendSwatch(cssVar("--series-4"), "start (S)"),
    legendSwatch(cssVar("--good"), "goal (G)"),
    legendSwatch(cssVar("--critical"), "cliff"),
  ]);
  card2.insertBefore(legend, gridWrap);

  const controls = el("div", { class: "controls" }, []);
  const snaps = gw.q_learning.snapshots;
  const slider = el("input", { type: "range", min: "0", max: String(snaps.length - 1), value: String(snaps.length - 1) }, []);
  const readout = el("div", { class: "readout" }, [""]);
  const playBtn = el("button", {}, ["▶ Play"]);
  const optimalToggle = el("label", { style: "display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text-secondary);cursor:pointer;" }, []);
  const optimalCheckbox = el("input", { type: "checkbox" }, []);
  optimalToggle.appendChild(optimalCheckbox);
  optimalToggle.appendChild(document.createTextNode("show DP-optimal policy instead"));
  controls.appendChild(playBtn);
  controls.appendChild(slider);
  controls.appendChild(readout);
  controls.appendChild(optimalToggle);
  card2.appendChild(controls);

  const ctx = canvas.getContext("2d");
  const cliffSet = new Set(gw.cliff.map(([r, c]) => r + "," + c));
  const startKey = gw.start[0] + "," + gw.start[1];
  const goalKey = gw.goal[0] + "," + gw.goal[1];

  function valueColor(v, vMin, vMax) {
    const t = Math.max(0, Math.min(1, (v - vMin) / (vMax - vMin || 1)));
    const steps = [cssVar("--seq-100"), cssVar("--seq-200"), cssVar("--seq-300"), cssVar("--seq-400"),
      cssVar("--seq-500"), cssVar("--seq-600"), cssVar("--seq-700")];
    const idx = Math.min(steps.length - 1, Math.floor(t * steps.length));
    return steps[idx];
  }

  const dpVals = Object.values(gw.dp_V);
  const vMin = Math.min(...dpVals), vMax = Math.max(...dpVals.filter((v) => v < 1));

  function drawGrid(Qtable, policy) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let r = 0; r < gw.rows; r++) {
      for (let c = 0; c < gw.cols; c++) {
        const key = r + "," + c;
        const s = r * gw.cols + c;
        const x = c * cell, y = r * cell;
        let fill = cssVar("--surface-2");
        if (cliffSet.has(key)) fill = cssVar("--critical");
        else if (key === goalKey) fill = cssVar("--good");
        else if (key === startKey) fill = cssVar("--series-4");
        else if (Qtable && Qtable[s]) {
          const v = Math.max(...Object.values(Qtable[s]));
          fill = valueColor(v, vMin, 0);
        }
        ctx.fillStyle = fill;
        ctx.fillRect(x + 1, y + 1, cell - 2, cell - 2);

        if (!cliffSet.has(key) && key !== goalKey && policy && policy[s] !== undefined) {
          drawArrow(ctx, x + cell / 2, y + cell / 2, policy[s], cliffSet.has(key) ? "#fff" : cssVar("--text-primary"));
        }
        if (key === startKey) label(ctx, x + cell / 2, y + cell / 2, "S");
        if (key === goalKey) label(ctx, x + cell / 2, y + cell / 2, "G");
      }
    }
  }

  function drawArrow(ctx, cx, cy, action, color) {
    // 0=up,1=right,2=down,3=left
    const dirs = { 0: [0, -1], 1: [1, 0], 2: [0, 1], 3: [-1, 0] };
    const [dx, dy] = dirs[action];
    const len = cell * 0.28;
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx - dx * len, cy - dy * len);
    ctx.lineTo(cx + dx * len, cy + dy * len);
    ctx.stroke();
    const ang = Math.atan2(dy, dx);
    ctx.beginPath();
    ctx.moveTo(cx + dx * len, cy + dy * len);
    ctx.lineTo(cx + dx * len - 6 * Math.cos(ang - 0.5), cy + dy * len - 6 * Math.sin(ang - 0.5));
    ctx.lineTo(cx + dx * len - 6 * Math.cos(ang + 0.5), cy + dy * len - 6 * Math.sin(ang + 0.5));
    ctx.closePath();
    ctx.fill();
  }
  function label(ctx, cx, cy, text) {
    ctx.fillStyle = "#fff";
    ctx.font = "bold 13px system-ui, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, cx, cy - cell * 0.28);
  }

  function refresh() {
    if (optimalCheckbox.checked) {
      readout.textContent = "DP-optimal policy";
      const vTable = {};
      for (const s of Object.keys(gw.dp_V)) vTable[s] = { 0: gw.dp_V[s] };
      drawGrid(vTable, gw.dp_policy);
      slider.disabled = true;
    } else {
      const snap = snaps[Number(slider.value)];
      readout.textContent = "episode " + snap.episode;
      drawGrid(snap.Q, snap.policy);
      slider.disabled = false;
    }
  }
  slider.addEventListener("input", refresh);
  optimalCheckbox.addEventListener("change", refresh);

  let playing = false, playTimer = null;
  playBtn.addEventListener("click", () => {
    playing = !playing;
    playBtn.textContent = playing ? "⏸ Pause" : "▶ Play";
    if (playing) {
      optimalCheckbox.checked = false;
      if (Number(slider.value) >= snaps.length - 1) slider.value = "0";
      playTimer = setInterval(() => {
        let v = Number(slider.value) + 1;
        if (v > snaps.length - 1) { v = snaps.length - 1; playing = false; playBtn.textContent = "▶ Play"; clearInterval(playTimer); }
        slider.value = String(v);
        refresh();
      }, 220);
    } else {
      clearInterval(playTimer);
    }
  });

  refresh();
}

function statTile(label, value, note, good) {
  const children = [
    el("div", { class: "label" }, [label]),
    el("div", { class: "value" + (good ? " good" : "") }, [value]),
  ];
  if (note) children.push(el("div", { class: "note" }, [note]));
  return el("div", { class: "stat-tile" }, children);
}
function legendSwatch(color, label) {
  return el("div", { class: "item" }, [el("div", { class: "swatch", style: "background:" + color }, []), label]);
}

/* ---------------------------------------------------------------------- */
/* CartPole tab -- JS mirror of bellman/envs.py's CartPoleEnv physics and  */
/* bellman/nn.py's MLP forward pass, so the trained policy can be driven   */
/* live in the browser with no server round trip.                          */
/* ---------------------------------------------------------------------- */
const CP = {
  GRAVITY: 9.8, MASSCART: 1.0, MASSPOLE: 0.1, LENGTH: 0.5,
  FORCE_MAG: 10.0, TAU: 0.02,
  X_THRESHOLD: 2.4, THETA_THRESHOLD: 12 * 2 * Math.PI / 360,
};
CP.TOTAL_MASS = CP.MASSCART + CP.MASSPOLE;
CP.POLEMASS_LENGTH = CP.MASSPOLE * CP.LENGTH;

function cartpoleStep(state, action) {
  let [x, xDot, theta, thetaDot] = state;
  const force = action === 1 ? CP.FORCE_MAG : -CP.FORCE_MAG;
  const costheta = Math.cos(theta), sintheta = Math.sin(theta);
  const temp = (force + CP.POLEMASS_LENGTH * thetaDot * thetaDot * sintheta) / CP.TOTAL_MASS;
  const thetaacc = (CP.GRAVITY * sintheta - costheta * temp) /
    (CP.LENGTH * (4.0 / 3.0 - CP.MASSPOLE * costheta * costheta / CP.TOTAL_MASS));
  const xacc = temp - CP.POLEMASS_LENGTH * thetaacc * costheta / CP.TOTAL_MASS;

  xDot += CP.TAU * xacc;
  x += CP.TAU * xDot;
  thetaDot += CP.TAU * thetaacc;
  theta += CP.TAU * thetaDot;

  const done = Math.abs(x) > CP.X_THRESHOLD || Math.abs(theta) > CP.THETA_THRESHOLD;
  return { state: [x, xDot, theta, thetaDot], done };
}

function mlpForward(weights, x) {
  let activations = x;
  for (let li = 0; li < weights.layers.length; li++) {
    const layer = weights.layers[li];
    const out = [];
    for (let o = 0; o < layer.W.length; o++) {
      let acc = layer.b[o];
      for (let i = 0; i < layer.W[o].length; i++) acc += layer.W[o][i] * activations[i];
      out.push(acc);
    }
    activations = li < weights.layers.length - 1 ? out.map((v) => Math.max(0, v)) : out;
  }
  return activations;
}
function argmax(arr) { return arr[0] > arr[1] ? 0 : 1; }

function renderCartpole() {
  const cp = DATA.cartpole;
  const root = document.getElementById("tab-cartpole");

  root.appendChild(el("div", { class: "stat-row" }, [
    statTile("Trained policy (eval mean)", fmt(cp.eval_mean, 1) + " steps",
      "held out over 30 episodes, cap " + cp.eval_cap, cp.eval_mean > cp.baseline_mean * 2),
    statTile("Random-policy baseline", fmt(cp.baseline_mean, 1) + " steps", "same 30-episode protocol"),
    statTile("Improvement", "×" + fmt(cp.eval_mean / cp.baseline_mean, 1),
      "trained vs. random, held-out episodes"),
    statTile("Training time", fmt(cp.train_time_sec, 1) + "s", cp.episodes + " episodes, pure-Python autodiff"),
  ]));

  const card1 = el("div", { class: "card" }, [
    el("h2", {}, ["Training curve"]),
    el("p", { class: "sub" }, [
      "Per-episode reward (= steps survived) during REINFORCE training, raw and smoothed (20-episode moving average).",
    ]),
  ]);
  root.appendChild(card1);
  drawLineChart(card1, [
    { label: "episode reward (raw)", color: cssVar("--text-muted"), data: cp.train_rewards },
    { label: "20-ep moving average", color: cssVar("--series-4"), data: movingAverage(cp.train_rewards, 20) },
  ], { xLabel: "episode" });

  const card2 = el("div", { class: "card" }, [
    el("h2", {}, ["Live balancing"]),
    el("p", { class: "sub" }, [
      "The exact physics (cartpoleStep) and the trained network's forward pass (mlpForward) re-implemented " +
      "in JavaScript from the same equations bellman/envs.py and bellman/nn.py use — no server round trip.",
    ]),
  ]);
  root.appendChild(card2);

  const canvas = el("canvas", { width: "760", height: "260" }, []);
  canvas.style.width = "100%";
  canvas.style.height = "260px";
  canvas.style.background = "var(--surface-2)";
  canvas.style.borderRadius = "8px";
  card2.appendChild(canvas);
  const ctx = canvas.getContext("2d");

  const controls = el("div", { class: "controls" }, []);
  const playBtn = el("button", {}, ["▶ Play"]);
  const resetBtn = el("button", {}, ["↺ New episode"]);
  const select = el("select", { style: "border-radius:8px;border:1px solid var(--border);padding:6px 8px;font-family:inherit;font-size:13px;background:var(--surface-2);color:var(--text-primary);" }, []);
  select.appendChild(el("option", { value: "trained" }, ["Trained policy"]));
  select.appendChild(el("option", { value: "random" }, ["Random baseline"]));
  const speedLabel = el("div", { class: "readout" }, ["speed 1×"]);
  const speed = el("input", { type: "range", min: "1", max: "4", value: "1", style: "max-width:120px;flex:none;" }, []);
  const status = el("div", { class: "readout" }, ["step 0"]);
  controls.appendChild(playBtn);
  controls.appendChild(resetBtn);
  controls.appendChild(select);
  controls.appendChild(speed);
  controls.appendChild(speedLabel);
  controls.appendChild(status);
  card2.appendChild(controls);

  let simState = [0, 0, 0, 0];
  let steps = 0, running = false, rafId = null, ended = false;

  function randInit() {
    return [0, 1, 2, 3].map(() => (Math.random() * 2 - 1) * 0.05);
  }
  function resetSim() {
    simState = randInit();
    steps = 0; ended = false;
    status.textContent = "step 0";
    draw();
  }

  function draw() {
    const w = 760, h = 260;
    ctx.clearRect(0, 0, w, h);
    const scale = 120; // px per meter
    const cx = w / 2, trackY = h * 0.62;
    ctx.strokeStyle = cssVar("--baseline");
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(20, trackY); ctx.lineTo(w - 20, trackY); ctx.stroke();

    const [x, , theta] = simState;
    const px = cx + x * scale;
    ctx.fillStyle = cssVar("--series-1");
    ctx.fillRect(px - 30, trackY - 15, 60, 28);

    const poleLen = 100;
    const tipX = px + Math.sin(theta) * poleLen;
    const tipY = trackY - 14 - Math.cos(theta) * poleLen;
    ctx.strokeStyle = cssVar("--series-2");
    ctx.lineWidth = 6;
    ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(px, trackY - 14); ctx.lineTo(tipX, tipY); ctx.stroke();
    ctx.fillStyle = cssVar("--series-2");
    ctx.beginPath(); ctx.arc(px, trackY - 14, 5, 0, Math.PI * 2); ctx.fill();

    if (Math.abs(x) > CP.X_THRESHOLD * 0.96) {
      ctx.fillStyle = cssVar("--critical");
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("near track limit", cx, 20);
    }
  }

  function tick() {
    const stepsPerFrame = Number(speed.value);
    for (let i = 0; i < stepsPerFrame && !ended; i++) {
      let action;
      if (select.value === "trained") {
        const logits = mlpForward(cp.policy_weights, simState);
        action = argmax(logits);
      } else {
        action = Math.random() < 0.5 ? 0 : 1;
      }
      const res = cartpoleStep(simState, action);
      simState = res.state;
      steps += 1;
      if (res.done || steps >= 500) { ended = true; }
    }
    status.textContent = ended ? `episode ended after ${steps} steps` : `step ${steps}`;
    draw();
    if (running && !ended) {
      rafId = requestAnimationFrame(tick);
    } else if (ended) {
      running = false;
      playBtn.textContent = "▶ Play";
    }
  }

  playBtn.addEventListener("click", () => {
    if (ended) resetSim();
    running = !running;
    playBtn.textContent = running ? "⏸ Pause" : "▶ Play";
    if (running) rafId = requestAnimationFrame(tick);
    else cancelAnimationFrame(rafId);
  });
  resetBtn.addEventListener("click", () => { running = false; cancelAnimationFrame(rafId); playBtn.textContent = "▶ Play"; resetSim(); });
  speed.addEventListener("input", () => { speedLabel.textContent = "speed " + speed.value + "×"; });
  select.addEventListener("change", () => resetSim());

  resetSim();
}

/* ---------------------------------------------------------------------- */
/* Blackjack tab                                                          */
/* ---------------------------------------------------------------------- */
function renderBlackjack() {
  const bj = DATA.blackjack;
  const root = document.getElementById("tab-blackjack");
  if (!bj) {
    root.appendChild(el("div", { class: "card" }, [el("p", { class: "sub" }, ["Blackjack stretch feature was not run for this build."])]));
    return;
  }

  root.appendChild(el("div", { class: "stat-row" }, [
    statTile("Agreement vs. optimal", fmt(bj.agreement * 100, 1) + "%", bj.states_compared + " states compared", bj.agreement === 1),
    statTile("Mismatches", String(bj.disagreements.length), bj.disagreements.length === 0 ? "exact match" : "see table below"),
    statTile("Training episodes", bj.episodes.toLocaleString(), "Monte Carlo Exploring Starts"),
  ]));

  const card = el("div", { class: "card" }, [
    el("h2", {}, ["Learned policy vs. independently-computed optimal"]),
    el("p", { class: "sub" }, [
      "Rows are the player's total, columns the dealer's up-card. Blue = stand, orange = hit. The optimal " +
      "policy is computed by exact expected-value backward induction over the dealer's outcome distribution " +
      "(bellman/dp.py) — code that shares nothing with the Monte Carlo learner. A red ring marks any cell " +
      "where the two disagree.",
    ]),
  ]);
  root.appendChild(card);

  const grids = el("div", { class: "grid-two" }, []);
  card.appendChild(grids);

  const mismatchSet = new Set(bj.disagreements.map((d) => d.state.join(",")));

  for (const usableAce of [false, true]) {
    const table = el("table", { class: "policy-grid" }, []);
    table.appendChild(el("caption", {}, [usableAce ? "Usable ace (soft hand)" : "No usable ace (hard hand)"]));
    const headRow = el("tr", {}, [el("th", {}, [""])]);
    for (let d = 1; d <= 10; d++) headRow.appendChild(el("th", {}, [d === 1 ? "A" : String(d)]));
    table.appendChild(headRow);
    for (let total = 21; total >= 12; total--) {
      const row = el("tr", {}, [el("th", {}, [String(total)])]);
      for (let d = 1; d <= 10; d++) {
        const key = [total, d, usableAce].join(",");
        const action = bj.learned_policy[key];
        const color = action === 1 ? cssVar("--series-2") : cssVar("--series-1");
        const mismatch = mismatchSet.has(key);
        const td = el("td", {
          style: `background:${color};` + (mismatch ? `box-shadow: inset 0 0 0 2px ${cssVar("--critical")};` : ""),
          title: `total ${total} vs dealer ${d}: ${action === 1 ? "hit" : "stand"}` + (mismatch ? " (MISMATCH)" : ""),
        }, []);
        row.appendChild(td);
      }
      table.appendChild(row);
    }
    grids.appendChild(table);
  }

  const legend = el("div", { class: "legend" }, [
    legendSwatch(cssVar("--series-1"), "stand"),
    legendSwatch(cssVar("--series-2"), "hit"),
  ]);
  card.insertBefore(legend, grids);
}

/* ---------------------------------------------------------------------- */
renderGridworld();
renderCartpole();
renderBlackjack();
