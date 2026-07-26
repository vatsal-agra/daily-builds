"use strict";

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const CANVAS_W = canvas.width;
const CANVAS_H = canvas.height;

const hudBodies = document.getElementById("hud-bodies");
const hudFps = document.getElementById("hud-fps");
const hudStatus = document.getElementById("hud-status");
const toastEl = document.getElementById("toast");

let latestState = { bodies: [], joints: [], contacts: [], gravity: [0, 520] };
let paused = false;
let debugOn = false;
let currentTool = "circle";

// ---------------------------------------------------------------------
// Networking
// ---------------------------------------------------------------------

function api(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }).then((r) => r.json().then((data) => {
    if (!r.ok) throw new Error(data.error || `request failed (${r.status})`);
    return data;
  }));
}

function connectEvents() {
  const es = new EventSource("/events");
  es.onmessage = (ev) => {
    try {
      latestState = JSON.parse(ev.data);
    } catch (e) { /* ignore malformed frame */ }
  };
  es.onerror = () => {
    hudStatus.textContent = "reconnecting…";
    hudStatus.className = "paused";
    // EventSource auto-reconnects; nothing else to do.
  };
}

function showToast(msg, ms = 2200) {
  toastEl.textContent = msg;
  toastEl.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { toastEl.hidden = true; }, ms);
}

// ---------------------------------------------------------------------
// Coordinate mapping
// ---------------------------------------------------------------------

function eventToWorld(ev) {
  const rect = canvas.getBoundingClientRect();
  const sx = CANVAS_W / rect.width;
  const sy = CANVAS_H / rect.height;
  return {
    x: (ev.clientX - rect.left) * sx,
    y: (ev.clientY - rect.top) * sy,
  };
}

// ---------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------

const PALETTE = ["#6ee7c8", "#7aa2f7", "#f6c177", "#f28b82", "#c792ea", "#89ddff"];

function colorFor(index) {
  return PALETTE[index % PALETTE.length];
}

function worldVertex(body, vx, vy) {
  const c = Math.cos(body.angle), s = Math.sin(body.angle);
  return [body.x + vx * c - vy * s, body.y + vx * s + vy * c];
}

let spawnPreview = null; // {tool, startX, startY, curX, curY}
let fpsLast = performance.now();
let fpsSmoothed = 0;

function draw() {
  const now = performance.now();
  const dt = now - fpsLast;
  fpsLast = now;
  if (dt > 0) {
    const inst = 1000 / dt;
    fpsSmoothed = fpsSmoothed === 0 ? inst : fpsSmoothed * 0.9 + inst * 0.1;
  }

  ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);

  // subtle grid
  ctx.strokeStyle = "rgba(255,255,255,0.03)";
  ctx.lineWidth = 1;
  for (let x = 0; x < CANVAS_W; x += 50) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, CANVAS_H); ctx.stroke();
  }
  for (let y = 0; y < CANVAS_H; y += 50) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(CANVAS_W, y); ctx.stroke();
  }

  const bodies = latestState.bodies || [];
  let dynamicIndex = 0;
  for (const b of bodies) {
    ctx.save();
    if (b.static) {
      ctx.fillStyle = "#232a3a";
      ctx.strokeStyle = "#323a4d";
    } else {
      const col = colorFor(dynamicIndex++);
      ctx.fillStyle = col + "cc";
      ctx.strokeStyle = col;
    }
    ctx.lineWidth = 2;

    if (b.shape === "circle") {
      ctx.beginPath();
      ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      // spin indicator
      const tip = worldVertex(b, b.radius, 0);
      ctx.beginPath();
      ctx.moveTo(b.x, b.y);
      ctx.lineTo(tip[0], tip[1]);
      ctx.strokeStyle = b.static ? "#3a4358" : "rgba(0,0,0,0.35)";
      ctx.stroke();
    } else {
      ctx.beginPath();
      const verts = b.vertices.map((v) => worldVertex(b, v[0], v[1]));
      ctx.moveTo(verts[0][0], verts[0][1]);
      for (let i = 1; i < verts.length; i++) ctx.lineTo(verts[i][0], verts[i][1]);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  // joints
  for (const j of latestState.joints || []) {
    ctx.beginPath();
    ctx.moveTo(j.pa[0], j.pa[1]);
    ctx.lineTo(j.pb[0], j.pb[1]);
    if (j.type === "SpringJoint") {
      ctx.strokeStyle = "rgba(122,162,247,0.8)";
      ctx.setLineDash([4, 4]);
    } else if (j.type === "PinJoint") {
      ctx.strokeStyle = "rgba(246,193,119,0.8)";
      ctx.setLineDash([]);
    } else {
      ctx.strokeStyle = "rgba(231,235,243,0.5)";
      ctx.setLineDash([]);
    }
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.setLineDash([]);
    // anchor dots
    ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath(); ctx.arc(j.pa[0], j.pa[1], 3, 0, Math.PI * 2); ctx.fill();
    if (j.type !== "SpringJoint" || latestState.joints.length < 200) {
      ctx.beginPath(); ctx.arc(j.pb[0], j.pb[1], 3, 0, Math.PI * 2); ctx.fill();
    }
  }

  if (debugOn) {
    // broad-phase spatial-hash grid (the actual cell size the engine uses)
    const cell = latestState.broadphase_cell_size || 64;
    ctx.strokeStyle = "rgba(246,193,119,0.18)";
    ctx.lineWidth = 1;
    for (let x = 0; x < CANVAS_W; x += cell) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, CANVAS_H); ctx.stroke();
    }
    for (let y = 0; y < CANVAS_H; y += cell) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(CANVAS_W, y); ctx.stroke();
    }

    // contact points + normals
    for (const c of latestState.contacts || []) {
      for (const p of c.points) {
        ctx.beginPath();
        ctx.arc(p[0], p[1], 4, 0, Math.PI * 2);
        ctx.fillStyle = "#f28b82";
        ctx.fill();
      }
      if (c.points.length) {
        const p = c.points[0];
        ctx.beginPath();
        ctx.moveTo(p[0], p[1]);
        ctx.lineTo(p[0] + c.normal[0] * 24, p[1] + c.normal[1] * 24);
        ctx.strokeStyle = "#f28b82";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }

    // velocity vectors
    ctx.strokeStyle = "#89ddff";
    ctx.lineWidth = 1.5;
    for (const b of bodies) {
      if (b.static) continue;
      const speed = Math.hypot(b.vx, b.vy);
      if (speed < 1) continue;
      const scale = 0.12;
      ctx.beginPath();
      ctx.moveTo(b.x, b.y);
      ctx.lineTo(b.x + b.vx * scale, b.y + b.vy * scale);
      ctx.stroke();
    }
  }

  // spawn preview
  if (spawnPreview) {
    ctx.save();
    ctx.strokeStyle = "rgba(110,231,200,0.9)";
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1.5;
    if (spawnPreview.tool === "circle") {
      const r = Math.max(6, Math.hypot(spawnPreview.curX - spawnPreview.startX, spawnPreview.curY - spawnPreview.startY));
      ctx.beginPath();
      ctx.arc(spawnPreview.startX, spawnPreview.startY, r, 0, Math.PI * 2);
      ctx.stroke();
    } else if (spawnPreview.tool === "box") {
      const w = Math.abs(spawnPreview.curX - spawnPreview.startX) * 2 || 10;
      const h = Math.abs(spawnPreview.curY - spawnPreview.startY) * 2 || 10;
      ctx.strokeRect(spawnPreview.startX - w / 2, spawnPreview.startY - h / 2, w, h);
    }
    ctx.restore();
  }

  hudBodies.textContent = `${bodies.length} bodies`;
  hudFps.textContent = `${Math.round(fpsSmoothed)} fps`;
  syncPausedUi(!!latestState.paused);

  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

// ---------------------------------------------------------------------
// Input: tool selection
// ---------------------------------------------------------------------

document.querySelectorAll(".tool-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tool-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentTool = btn.dataset.tool;
    canvas.classList.toggle("tool-grab", currentTool === "grab");
  });
});

// ---------------------------------------------------------------------
// Input: canvas pointer handling (spawn-drag / grab-drag)
// ---------------------------------------------------------------------

let dragMode = null; // "spawn" | "grab" | null
let grabbed = false;

canvas.addEventListener("pointerdown", (ev) => {
  const p = eventToWorld(ev);
  canvas.setPointerCapture(ev.pointerId);
  if (currentTool === "grab") {
    dragMode = "grab";
    api("/api/grab", { x: p.x, y: p.y }).then((res) => {
      grabbed = !!res.grabbed;
      canvas.classList.toggle("dragging", grabbed);
      if (!grabbed) showToast("Nothing there to grab");
    }).catch((e) => showToast(e.message));
  } else {
    dragMode = "spawn";
    spawnPreview = { tool: currentTool, startX: p.x, startY: p.y, curX: p.x, curY: p.y };
  }
});

canvas.addEventListener("pointermove", (ev) => {
  const p = eventToWorld(ev);
  if (dragMode === "grab" && grabbed) {
    api("/api/drag", { x: p.x, y: p.y }).catch(() => {});
  } else if (dragMode === "spawn" && spawnPreview) {
    spawnPreview.curX = p.x;
    spawnPreview.curY = p.y;
  }
});

function endDrag(ev) {
  const p = eventToWorld(ev);
  if (dragMode === "grab") {
    if (grabbed) api("/api/release", {}).catch(() => {});
    grabbed = false;
    canvas.classList.remove("dragging");
  } else if (dragMode === "spawn" && spawnPreview) {
    const sp = spawnPreview;
    const restitution = parseFloat(document.getElementById("restitution").value);
    const friction = parseFloat(document.getElementById("friction").value);
    if (sp.tool === "circle") {
      const r = Math.max(6, Math.min(60, Math.hypot(p.x - sp.startX, p.y - sp.startY)));
      api("/api/spawn", { shape: "circle", x: sp.startX, y: sp.startY, radius: r, restitution, friction })
        .catch((e) => showToast(e.message));
    } else if (sp.tool === "box") {
      const w = Math.max(10, Math.min(140, Math.abs(p.x - sp.startX) * 2)) || 40;
      const h = Math.max(10, Math.min(140, Math.abs(p.y - sp.startY) * 2)) || 40;
      api("/api/spawn", { shape: "box", x: sp.startX, y: sp.startY, w, h, restitution, friction })
        .catch((e) => showToast(e.message));
    }
    spawnPreview = null;
  }
  dragMode = null;
}

canvas.addEventListener("pointerup", endDrag);
canvas.addEventListener("pointercancel", endDrag);
canvas.addEventListener("pointerleave", (ev) => {
  if (dragMode === "spawn") { spawnPreview = null; dragMode = null; }
});

// ---------------------------------------------------------------------
// Sliders
// ---------------------------------------------------------------------

function wireSlider(id, outId, fmt, onChange) {
  const el = document.getElementById(id);
  const out = document.getElementById(outId);
  const update = () => {
    out.textContent = fmt(parseFloat(el.value));
    onChange(parseFloat(el.value));
  };
  el.addEventListener("input", update);
  update();
}

wireSlider("restitution", "restitution-val", (v) => v.toFixed(2), (v) => {
  api("/api/params", { restitution: v }).catch(() => {});
});
wireSlider("friction", "friction-val", (v) => v.toFixed(2), (v) => {
  api("/api/params", { friction: v }).catch(() => {});
});
wireSlider("gravity", "gravity-val", (v) => Math.round(v).toString(), (v) => {
  api("/api/params", { gravity: v }).catch(() => {});
});

// ---------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------

const btnPause = document.getElementById("btn-pause");

function syncPausedUi(isPaused) {
  if (isPaused === paused) return;
  paused = isPaused;
  btnPause.textContent = paused ? "Resume" : "Pause";
  hudStatus.textContent = paused ? "paused" : "running";
  hudStatus.className = paused ? "paused" : "running";
}

btnPause.addEventListener("click", () => {
  api("/api/pause", { paused: !paused }).then((res) => syncPausedUi(res.paused));
});

document.getElementById("btn-step").addEventListener("click", () => {
  api("/api/step", {}).then(() => syncPausedUi(true));
});

document.getElementById("btn-reset").addEventListener("click", () => {
  api("/api/reset", {}).then(() => showToast("Scene reset"));
});

document.getElementById("debug-toggle").addEventListener("change", (ev) => {
  debugOn = ev.target.checked;
});

// ---------------------------------------------------------------------
// Scenes
// ---------------------------------------------------------------------

fetch("/api/scenes").then((r) => r.json()).then((data) => {
  const wrap = document.getElementById("scene-buttons");
  (data.scenes || []).forEach((name) => {
    const btn = document.createElement("button");
    btn.textContent = name[0].toUpperCase() + name.slice(1);
    btn.addEventListener("click", () => {
      api("/api/scene/load", { name }).then(() => showToast(`Loaded "${name}"`)).catch((e) => showToast(e.message));
    });
    wrap.appendChild(btn);
  });
});

document.getElementById("btn-export").addEventListener("click", () => {
  fetch("/api/scene/export").then((r) => r.json()).then((data) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "impulse-scene.json";
    a.click();
    URL.revokeObjectURL(url);
    showToast("Scene exported");
  });
});

document.getElementById("btn-import").addEventListener("click", () => {
  document.getElementById("file-import").click();
});

document.getElementById("file-import").addEventListener("change", (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  file.text().then((text) => {
    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      showToast("Not valid JSON");
      return;
    }
    api("/api/scene/import", data).then(() => showToast("Scene loaded")).catch((e) => showToast(e.message));
  });
  ev.target.value = "";
});

connectEvents();
