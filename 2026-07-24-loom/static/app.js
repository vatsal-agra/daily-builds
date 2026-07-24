(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function isDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `request to ${url} failed (${res.status})`);
    }
    return data;
  }

  async function getJSON(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `request to ${url} failed (${res.status})`);
    }
    return data;
  }

  // ---------------- status + loss chart ----------------

  function renderStats(status) {
    const items = [
      ["params", status.num_params.toLocaleString()],
      ["vocab size", status.vocab_size],
      ["layers", status.n_layer],
      ["heads", status.n_head],
      ["embd dim", status.n_embd],
      ["context", status.block_size],
      ["step", `${status.step ?? "?"} / ${status.max_steps ?? "?"}`],
    ];
    $("stats").innerHTML = items
      .map(([label, val]) => `<div class="stat">${label}<b>${val}</b></div>`)
      .join("");
  }

  function drawChart(history, baseline) {
    const canvas = $("chart");
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    const dim = isDark();
    const gridColor = dim ? "#2a2f3d" : "#dde0ea";
    const textColor = dim ? "#9aa1b4" : "#5b6072";

    const pad = { l: 44, r: 16, t: 14, b: 26 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;

    if (!history || history.length === 0) {
      ctx.fillStyle = textColor;
      ctx.font = "13px monospace";
      ctx.fillText("no training history yet", pad.l, H / 2);
      return;
    }

    const steps = history.map((h) => h.step);
    const allLoss = history.flatMap((h) => [h.train_loss, h.val_loss]).concat([baseline]);
    const maxStep = Math.max(...steps);
    const minLoss = Math.min(...allLoss) * 0.92;
    const maxLoss = Math.max(...allLoss) * 1.04;

    const xOf = (s) => pad.l + (s / Math.max(maxStep, 1)) * plotW;
    const yOf = (l) => pad.t + (1 - (l - minLoss) / Math.max(maxLoss - minLoss, 1e-6)) * plotH;

    // grid + y labels
    ctx.strokeStyle = gridColor;
    ctx.fillStyle = textColor;
    ctx.font = "11px monospace";
    ctx.lineWidth = 1;
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) {
      const l = minLoss + (i / ticks) * (maxLoss - minLoss);
      const y = yOf(l);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(W - pad.r, y);
      ctx.stroke();
      ctx.fillText(l.toFixed(2), 4, y + 4);
    }

    // baseline dashed line
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = "#7d8296";
    ctx.beginPath();
    ctx.moveTo(pad.l, yOf(baseline));
    ctx.lineTo(W - pad.r, yOf(baseline));
    ctx.stroke();
    ctx.restore();

    function line(key, color) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      history.forEach((h, i) => {
        const x = xOf(h.step), y = yOf(h[key]);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = color;
      history.forEach((h) => {
        ctx.beginPath();
        ctx.arc(xOf(h.step), yOf(h[key]), 2.5, 0, 7);
        ctx.fill();
      });
    }
    line("train_loss", "#7c9cff");
    line("val_loss", "#f6a95f");

    // x labels
    ctx.fillStyle = textColor;
    ctx.fillText("0", pad.l, H - 8);
    ctx.fillText(String(maxStep), W - pad.r - 30, H - 8);
  }

  async function refreshStatus() {
    try {
      const status = await getJSON("/api/status");
      renderStats(status);
      drawChart(status.history, status.baseline_loss);
      return status;
    } catch (e) {
      $("stats").innerHTML = `<div class="error-box">failed to load model status: ${e.message}</div>`;
    }
  }

  // ---------------- generation ----------------

  function wireSlider(id, valId, fmt) {
    const el = $(id), out = $(valId);
    const update = () => (out.textContent = fmt(parseFloat(el.value)));
    el.addEventListener("input", update);
    update();
  }

  wireSlider("temp", "temp-val", (v) => v.toFixed(2));
  wireSlider("topk", "topk-val", (v) => (v === 0 ? "0 (off)" : String(v)));
  wireSlider("topp", "topp-val", (v) => (v === 0 ? "0.00 (off)" : v.toFixed(2)));
  wireSlider("len", "len-val", (v) => String(v));

  async function runGenerate() {
    const btn = $("gen-btn");
    const out = $("gen-output");
    const meta = $("gen-meta");
    const prompt = $("prompt").value;
    btn.disabled = true;
    out.innerHTML = `<span class="spinner"></span> generating…`;
    meta.textContent = "";
    try {
      const data = await postJSON("/api/generate", {
        prompt,
        temperature: parseFloat($("temp").value),
        top_k: parseInt($("topk").value, 10),
        top_p: parseFloat($("topp").value),
        max_new_tokens: parseInt($("len").value, 10),
      });
      const promptPart = data.text.slice(0, data.prompt.length);
      const genPart = data.text.slice(data.prompt.length);
      out.innerHTML =
        `<span class="prompt-part">${escapeHtml(promptPart)}</span><span class="gen-part">${escapeHtml(genPart)}</span>`;
      meta.textContent = `${data.text.length} chars generated in ${data.elapsed_s.toFixed(2)}s`;
    } catch (e) {
      out.innerHTML = `<span class="placeholder">generation failed</span>`;
      meta.innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false;
    }
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  $("gen-btn").addEventListener("click", runGenerate);
  $("gen-clear").addEventListener("click", () => {
    $("prompt").value = "";
    $("gen-output").innerHTML = `<span class="placeholder">Generated text will appear here…</span>`;
    $("gen-meta").textContent = "";
  });

  // ---------------- attention visualizer ----------------

  let attnState = null; // { tokens, layers }
  let selectedLayer = 0, selectedHead = 0;

  function buildSelectors() {
    const nLayers = attnState.layers.length;
    const nHeads = attnState.layers[0].length;
    $("layer-select").innerHTML = Array.from({ length: nLayers }, (_, i) =>
      `<button data-l="${i}" class="${i === selectedLayer ? "active" : ""}">L${i}</button>`
    ).join("");
    $("head-select").innerHTML = Array.from({ length: nHeads }, (_, i) =>
      `<button data-h="${i}" class="${i === selectedHead ? "active" : ""}">H${i}</button>`
    ).join("");
    $("layer-select").querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => { selectedLayer = parseInt(b.dataset.l, 10); buildSelectors(); drawHeatmap(); })
    );
    $("head-select").querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => { selectedHead = parseInt(b.dataset.h, 10); buildSelectors(); drawHeatmap(); })
    );
  }

  function drawHeatmap() {
    const matrix = attnState.layers[selectedLayer][selectedHead]; // (T, T)
    const T = matrix.length;
    const canvas = $("heatmap");
    const cell = Math.max(4, Math.min(28, Math.floor(400 / T)));
    canvas.width = cell * T;
    canvas.height = cell * T;
    const ctx = canvas.getContext("2d");
    const dim = isDark();

    for (let i = 0; i < T; i++) {
      for (let j = 0; j < T; j++) {
        const w = matrix[i][j]; // 0..1
        const c = colorFor(w, dim);
        ctx.fillStyle = c;
        ctx.fillRect(j * cell, i * cell, cell, cell);
      }
    }
    const tokenList = attnState.tokens
      .map((t, i) => `${i}:${JSON.stringify(t)}`)
      .join("  ");
    const note = attnState.truncated
      ? `<div class="meta-line">prompt truncated to the model's ${T}-token context window</div>`
      : "";
    $("tokens-strip").innerHTML = `${escapeHtml(tokenList)}${note}`;
  }

  function colorFor(w, dim) {
    // 0 -> panel background, 1 -> accent color, simple lerp
    const t = Math.max(0, Math.min(1, w));
    const bg = dim ? [22, 25, 34] : [255, 255, 255];
    const hot = [124, 156, 255];
    const r = Math.round(bg[0] + (hot[0] - bg[0]) * t);
    const g = Math.round(bg[1] + (hot[1] - bg[1]) * t);
    const b = Math.round(bg[2] + (hot[2] - bg[2]) * t);
    return `rgb(${r},${g},${b})`;
  }

  async function runAttention() {
    const btn = $("attn-btn");
    const prompt = $("attn-prompt").value;
    btn.disabled = true;
    try {
      const data = await postJSON("/api/attention", { prompt });
      attnState = { tokens: data.tokens, layers: data.layers, truncated: data.truncated };
      selectedLayer = 0;
      selectedHead = 0;
      buildSelectors();
      drawHeatmap();
    } catch (e) {
      $("tokens-strip").innerHTML = `<div class="error-box">${escapeHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false;
    }
  }

  $("attn-btn").addEventListener("click", runAttention);

  // ---------------- init ----------------

  refreshStatus();
  setInterval(refreshStatus, 5000); // pick up live training progress
  runAttention(); // populate the visualizer with the default prompt on load
})();
