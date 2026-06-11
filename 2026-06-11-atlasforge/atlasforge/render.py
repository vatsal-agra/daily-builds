"""Render a World to a self-contained interactive HTML map.

Raster layers (biome/elevation/temperature/moisture) are encoded as PNGs and
embedded base64 inside an SVG; coastlines, rivers and settlements are vector
overlays. The HTML shell adds pan/zoom, a layer switcher, hover inspection
and a legend — all inline, no external assets.
"""

from __future__ import annotations

import base64
import json
import math

from .biomes import ALL_BIOMES, BIOME_COLORS, LAKE, OCEAN, SHALLOWS
from .png import encode_png
from .worldgen import World

WATER_BIOMES = {OCEAN, SHALLOWS, LAKE}


# ---------------------------------------------------------------- rasters

def _hillshade(world: World) -> list[float]:
    """Lambert-ish shading factor per cell, light from the northwest."""
    w, h, e = world.width, world.height, world.elevation
    shade = [1.0] * (w * h)
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if not world.is_land(i):
                continue
            ex = e[min(x + 1, w - 1) + y * w] - e[max(x - 1, 0) + y * w]
            ey = e[x + min(y + 1, h - 1) * w] - e[x + max(y - 1, 0) * w]
            s = 1.0 - (ex + ey) * 14.0
            shade[i] = min(1.22, max(0.62, s))
    return shade


def _shade_color(rgb: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(min(255, max(0, int(c * f))) for c in rgb)


def biome_pixels(world: World) -> list[tuple[int, int, int]]:
    shade = _hillshade(world)
    px = []
    for i, b in enumerate(world.biome):
        base = BIOME_COLORS[b]
        if b == OCEAN:
            # Depth-shaded ocean.
            depth = (world.sea_level - world.elevation[i]) / max(1e-9, world.sea_level)
            f = 1.0 - min(0.45, depth * 0.9)
            px.append(_shade_color(base, f))
        elif b in WATER_BIOMES:
            px.append(base)
        else:
            px.append(_shade_color(base, shade[i]))
    return px


def _ramp(stops: list[tuple[float, tuple[int, int, int]]], t: float) -> tuple[int, int, int]:
    t = min(1.0, max(0.0, t))
    for k in range(len(stops) - 1):
        t0, c0 = stops[k]
        t1, c1 = stops[k + 1]
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(int(c0[j] + (c1[j] - c0[j]) * f) for j in range(3))
    return stops[-1][1]


ELEV_RAMP = [
    (0.0, (24, 48, 86)), (0.35, (60, 110, 150)), (0.5, (96, 154, 102)),
    (0.65, (170, 168, 110)), (0.8, (150, 120, 90)), (0.92, (180, 176, 170)),
    (1.0, (250, 250, 250)),
]
TEMP_RAMP = [
    (0.0, (40, 60, 140)), (0.35, (90, 150, 190)), (0.55, (220, 210, 130)),
    (0.75, (230, 140, 70)), (1.0, (180, 40, 40)),
]
MOIST_RAMP = [
    (0.0, (190, 160, 90)), (0.45, (150, 175, 120)), (0.7, (80, 150, 140)),
    (1.0, (30, 90, 160)),
]


def field_pixels(world: World, values: list[float], ramp) -> list[tuple[int, int, int]]:
    px = []
    for i, v in enumerate(values):
        if world.is_land(i):
            px.append(_ramp(ramp, v))
        else:
            px.append(_shade_color(_ramp(ramp, v), 0.45))
    return px


def _png_data_uri(world: World, px: list[tuple[int, int, int]]) -> str:
    data = encode_png(world.width, world.height, px)
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------- vectors

def coastline_path(world: World) -> str:
    """One SVG path of all land/water cell boundaries (4-neighborhood)."""
    w, h = world.width, world.height
    segs = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if not world.is_land(i):
                continue
            if x == 0 or not world.is_land(i - 1):
                segs.append(f"M{x} {y}v1")
            if x == w - 1 or not world.is_land(i + 1):
                segs.append(f"M{x + 1} {y}v1")
            if y == 0 or not world.is_land(i - w):
                segs.append(f"M{x} {y}h1")
            if y == h - 1 or not world.is_land(i + w):
                segs.append(f"M{x} {y + 1}h1")
    return "".join(segs)


def river_segments(world: World) -> list[tuple[float, float, float, float, float]]:
    """(x1, y1, x2, y2, stroke_width) for each river reach, widening downstream."""
    acc = world.hydrology.accumulation
    if not world.hydrology.rivers:
        return []
    peak = max(max(acc[i] for i in path) for path in world.hydrology.rivers)
    segs = []
    w = world.width
    for path in world.hydrology.rivers:
        for a, b in zip(path, path[1:]):
            x1, y1 = a % w + 0.5, a // w + 0.5
            x2, y2 = b % w + 0.5, b // w + 0.5
            width = 0.16 + 0.55 * math.sqrt(acc[a] / peak)
            segs.append((x1, y1, x2, y2, round(width, 3)))
    return segs


# ---------------------------------------------------------------- stats

def world_stats(world: World) -> dict:
    n = world.width * world.height
    land = sum(1 for i in range(n) if world.is_land(i))
    lakes = sum(1 for v in world.hydrology.lake if v)
    present = sorted(
        {b for b in world.biome if b not in WATER_BIOMES},
        key=ALL_BIOMES.index,
    )
    return {
        "land_pct": round(100.0 * land / n, 1),
        "rivers": len(world.hydrology.rivers),
        "lake_cells": lakes,
        "biomes": present,
    }


# ---------------------------------------------------------------- html

def _hex2(v: int) -> str:
    return format(min(255, max(0, v)), "02x")


def _pack_field(values: list[float]) -> str:
    """Quantize floats in [0,1] to two hex digits per cell."""
    return "".join(_hex2(int(v * 255)) for v in values)


def render_html(world: World, title: str | None = None) -> str:
    stats = world_stats(world)
    title = title or f"Atlasforge — world {world.seed}"
    biome_index = {b: k for k, b in enumerate(ALL_BIOMES)}
    packed = {
        "elev": _pack_field(world.elevation),
        "temp": _pack_field(world.temperature),
        "moist": _pack_field(world.moisture),
        "biome": "".join(_hex2(biome_index[b]) for b in world.biome),
    }
    layers = {
        "biome": _png_data_uri(world, biome_pixels(world)),
        "elevation": _png_data_uri(world, field_pixels(world, world.elevation, ELEV_RAMP)),
        "temperature": _png_data_uri(world, field_pixels(world, world.temperature, TEMP_RAMP)),
        "moisture": _png_data_uri(world, field_pixels(world, world.moisture, MOIST_RAMP)),
    }
    rivers_svg = "".join(
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke-width="{sw}"/>'
        for x1, y1, x2, y2, sw in river_segments(world)
    )
    settlements_svg, gazetteer_html = _settlement_markup(world)
    present = sorted(set(world.biome), key=ALL_BIOMES.index)
    legend_html = "".join(
        f'<div class="key"><span style="background:rgb{BIOME_COLORS[b]}"></span>{b}</div>'
        for b in present
    )
    images_svg = "".join(
        f'<image id="layer-{name}" href="{uri}" x="0" y="0" '
        f'width="{world.width}" height="{world.height}" '
        f'style="image-rendering:pixelated" opacity="{1 if name == "biome" else 0}"/>'
        for name, uri in layers.items()
    )
    meta = {
        "width": world.width,
        "height": world.height,
        "seed": world.seed,
        "seaLevel": round(world.sea_level, 4),
        "biomeNames": ALL_BIOMES,
        "stats": stats,
    }
    html = (
        _TEMPLATE
        .replace("__TITLE__", _esc(title))
        .replace("__W__", str(world.width))
        .replace("__H__", str(world.height))
        .replace("__META__", json.dumps(meta))
        .replace("__PACKED__", json.dumps(packed))
        .replace("__IMAGES__", images_svg)
        .replace("__COAST__", coastline_path(world))
        .replace("__RIVERS__", rivers_svg)
        .replace("__SETTLEMENTS__", settlements_svg)
        .replace("__GAZETTEER__", gazetteer_html)
        .replace("__LEGEND__", legend_html)
        .replace(
            "__SUBTITLE__",
            f'seed {world.seed} · {world.width}×{world.height} · '
            f'{stats["land_pct"]}% land · {stats["rivers"]} rivers · '
            f'{len(stats["biomes"])} biomes',
        )
    )
    return html


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _settlement_markup(world: World) -> tuple[str, str]:
    if not world.settlements:
        return "", '<p class="empty">No settlements on this map.</p>'
    marks, rows = [], []
    radius = {"capital": 1.5, "town": 1.0, "village": 0.65}
    for s in sorted(world.settlements, key=lambda s: -s.population):
        r = radius.get(s.kind, 0.8)
        cx, cy = s.x + 0.5, s.y + 0.5
        cls = f"settle {s.kind}"
        marks.append(
            f'<g class="{cls}"><circle cx="{cx}" cy="{cy}" r="{r}"/>'
            f'<text x="{cx}" y="{cy - r - 0.6}">{_esc(s.name)}</text></g>'
        )
        rows.append(
            f'<div class="town" data-x="{s.x}" data-y="{s.y}">'
            f'<b>{_esc(s.name)}</b> <i>{s.kind}</i>'
            f'<span>pop. {s.population:,} · founded AF {s.founded}</span>'
            f'<em>{_esc(s.note)}</em></div>'
        )
    return "".join(marks), "".join(rows)


def write_html(world: World, path: str, title: str | None = None) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(world, title))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #10141c; --panel: #181e2a; --panel2: #1f2736; --ink: #dde4f0;
    --muted: #8b96ad; --accent: #6fb3ff; --line: #2a3447;
  }
  * { box-sizing: border-box; margin: 0; }
  body {
    background: var(--bg); color: var(--ink); height: 100vh;
    font: 14px/1.45 "Avenir Next", "Segoe UI", system-ui, sans-serif;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    padding: 10px 18px; border-bottom: 1px solid var(--line);
    display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
    background: var(--panel);
  }
  header h1 { font-size: 17px; font-weight: 600; letter-spacing: .4px; }
  header h1::before { content: "⬢ "; color: var(--accent); }
  header .sub { color: var(--muted); font-size: 12.5px; }
  main { flex: 1; display: flex; min-height: 0; }
  #map-wrap { flex: 1; position: relative; overflow: hidden; cursor: grab; background:
    radial-gradient(ellipse at 30% 20%, #141a26 0%, #0c0f16 100%); }
  #map-wrap.dragging { cursor: grabbing; }
  svg { width: 100%; height: 100%; display: block; }
  #coast { fill: none; stroke: rgba(12, 18, 26, .55); stroke-width: .22; }
  #rivers line { stroke: #7ec3e8; stroke-linecap: round; opacity: .92; }
  .settle circle { fill: #f3ead2; stroke: #2c2418; stroke-width: .22; }
  .settle.capital circle { fill: #ffd76e; }
  .settle text {
    font-size: 2.6px; fill: #fdf8ec; text-anchor: middle;
    paint-order: stroke; stroke: rgba(10, 14, 20, .85); stroke-width: .55px;
    font-family: Georgia, serif; letter-spacing: .08px;
    transition: opacity .25s; pointer-events: none;
  }
  .settle.village text { font-size: 2px; opacity: 0; }
  svg.zoomed .settle.village text { opacity: 1; }
  #compass {
    position: absolute; top: 14px; left: 14px; width: 44px; height: 44px;
    color: #cdd8ea; opacity: .85; pointer-events: none;
  }
  aside {
    width: 280px; border-left: 1px solid var(--line); background: var(--panel);
    display: flex; flex-direction: column; min-height: 0;
  }
  aside section { padding: 12px 16px; border-bottom: 1px solid var(--line); }
  aside h2 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--muted); margin-bottom: 8px;
  }
  .layers { display: flex; gap: 6px; flex-wrap: wrap; }
  .layers button {
    background: var(--panel2); color: var(--ink); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 10px; font-size: 12.5px; cursor: pointer;
  }
  .layers button.active { background: var(--accent); color: #0b1018; border-color: var(--accent); font-weight: 600; }
  #inspect { min-height: 86px; }
  #inspect .biome-name { font-size: 15px; font-weight: 600; color: var(--accent); }
  #inspect .vals { color: var(--muted); font-size: 12.5px; margin-top: 4px; }
  #legend { overflow-y: auto; flex: 0 1 auto; }
  .key { display: flex; align-items: center; gap: 8px; font-size: 12.5px; padding: 2px 0; color: var(--muted); }
  .key span { width: 14px; height: 14px; border-radius: 3px; display: inline-block; border: 1px solid rgba(255,255,255,.12); }
  #gazetteer { overflow-y: auto; flex: 1 1 auto; }
  #gazetteer .town { padding: 6px 8px; border-radius: 6px; cursor: pointer; }
  #gazetteer .town:hover { background: var(--panel2); }
  #gazetteer .town b { font-size: 13.5px; }
  #gazetteer .town i { color: var(--accent); font-size: 11.5px; margin-left: 6px; }
  #gazetteer .town span { display: block; color: var(--muted); font-size: 11.5px; }
  #gazetteer .town em { display: block; color: #aab6cc; font-size: 11.5px; font-style: italic; }
  #gazetteer .empty { color: var(--muted); font-size: 12.5px; }
  footer { padding: 6px 18px; color: var(--muted); font-size: 11.5px; border-top: 1px solid var(--line); background: var(--panel); }
  kbd {
    background: var(--panel2); border: 1px solid var(--line); border-radius: 4px;
    padding: 0 5px; font: 10.5px ui-monospace, monospace; color: var(--ink);
  }
  #crosshair { fill: none; stroke: #fff; stroke-width: .14; opacity: 0; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub">__SUBTITLE__</div>
</header>
<main>
  <div id="map-wrap">
    <svg id="map" viewBox="0 0 __W__ __H__" preserveAspectRatio="xMidYMid meet">
      __IMAGES__
      <path id="coast" d="__COAST__"/>
      <g id="rivers">__RIVERS__</g>
      <g id="settlements">__SETTLEMENTS__</g>
      <rect id="crosshair" width="1" height="1"/>
    </svg>
    <svg id="compass" viewBox="0 0 40 40">
      <circle cx="20" cy="20" r="17" fill="none" stroke="currentColor" stroke-width="1.2"/>
      <path d="M20 6 L24 22 L20 18 L16 22 Z" fill="currentColor"/>
      <text x="20" y="33" text-anchor="middle" font-size="9" fill="currentColor"
        font-family="Georgia, serif">N</text>
    </svg>
  </div>
  <aside>
    <section>
      <h2>Layer</h2>
      <div class="layers" id="layer-buttons">
        <button data-layer="biome" class="active">Biomes</button>
        <button data-layer="elevation">Elevation</button>
        <button data-layer="temperature">Temperature</button>
        <button data-layer="moisture">Rainfall</button>
      </div>
    </section>
    <section id="inspect">
      <h2>Inspector</h2>
      <div class="biome-name">Hover the map</div>
      <div class="vals">elevation · temperature · rainfall</div>
    </section>
    <section id="legend"><h2>Biomes present</h2>__LEGEND__</section>
    <section id="gazetteer"><h2>Gazetteer</h2>__GAZETTEER__</section>
  </aside>
</main>
<footer>Drag to pan · scroll to zoom · double-click or <kbd>0</kbd> to reset · keys <kbd>1</kbd>–<kbd>4</kbd> switch layers · zoom in to reveal village names · generated offline by Atlasforge (pure Python, zero deps)</footer>
<script>
"use strict";
const META = __META__;
const PACKED = __PACKED__;
const W = META.width, H = META.height;
const svg = document.getElementById("map");
const wrap = document.getElementById("map-wrap");
const crosshair = document.getElementById("crosshair");
const HOME = { x: 0, y: 0, w: W, h: H };
let vb = { ...HOME };

function applyVB() {
  svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  svg.classList.toggle("zoomed", vb.w < W / 2.5);
}
function clientToMap(ev) {
  if (typeof DOMPoint === "undefined" || !svg.getScreenCTM) return null;
  const m = svg.getScreenCTM();
  if (!m) return null;
  const p = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(m.inverse());
  return { x: p.x, y: p.y };
}

// --- pan ---
let drag = null;
wrap.addEventListener("pointerdown", (ev) => {
  drag = { sx: ev.clientX, sy: ev.clientY, vx: vb.x, vy: vb.y, moved: false };
  wrap.classList.add("dragging");
  wrap.setPointerCapture?.(ev.pointerId);
});
wrap.addEventListener("pointermove", (ev) => {
  if (drag) {
    const scale = vb.w / (wrap.clientWidth || 1);
    const dx = (ev.clientX - drag.sx) * scale, dy = (ev.clientY - drag.sy) * scale;
    if (Math.abs(dx) + Math.abs(dy) > 0.01) drag.moved = true;
    vb.x = drag.vx - dx; vb.y = drag.vy - dy;
    applyVB();
  }
  inspect(ev);
});
wrap.addEventListener("pointerup", () => { drag = null; wrap.classList.remove("dragging"); });
wrap.addEventListener("pointerleave", () => {
  crosshair.style.opacity = 0;
});

// --- zoom ---
wrap.addEventListener("wheel", (ev) => {
  ev.preventDefault();
  const p = clientToMap(ev);
  if (!p) return;
  const f = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
  const nw = Math.min(W * 4, Math.max(6, vb.w * f));
  const k = nw / vb.w;
  vb = { x: p.x - (p.x - vb.x) * k, y: p.y - (p.y - vb.y) * k, w: nw, h: vb.h * k };
  applyVB();
}, { passive: false });
wrap.addEventListener("dblclick", () => { vb = { ...HOME }; applyVB(); });

// --- layers ---
const LAYERS = ["biome", "elevation", "temperature", "moisture"];
function setLayer(layer) {
  for (const b of document.querySelectorAll("#layer-buttons button"))
    b.classList.toggle("active", b.dataset.layer === layer);
  for (const name of LAYERS)
    document.getElementById("layer-" + name)
      .setAttribute("opacity", name === layer ? 1 : 0);
}
document.getElementById("layer-buttons").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (btn) setLayer(btn.dataset.layer);
});
document.addEventListener("keydown", (ev) => {
  if (ev.target.tagName === "INPUT" || ev.metaKey || ev.ctrlKey) return;
  const k = LAYERS[+ev.key - 1];
  if (k) setLayer(k);
  if (ev.key === "0") { vb = { ...HOME }; applyVB(); }
});

// --- inspector ---
function unpack(key, i) { return parseInt(PACKED[key].slice(i * 2, i * 2 + 2), 16); }
const nameEl = document.querySelector("#inspect .biome-name");
const valsEl = document.querySelector("#inspect .vals");
function inspect(ev) {
  const p = clientToMap(ev);
  if (!p) return;
  const cx = Math.floor(p.x), cy = Math.floor(p.y);
  if (cx < 0 || cy < 0 || cx >= W || cy >= H) { crosshair.style.opacity = 0; return; }
  const i = cy * W + cx;
  crosshair.setAttribute("x", cx); crosshair.setAttribute("y", cy);
  crosshair.style.opacity = 1;
  const biome = META.biomeNames[unpack("biome", i)] || "?";
  const elev = unpack("elev", i) / 255, t = unpack("temp", i) / 255, m = unpack("moist", i) / 255;
  const meters = Math.round((elev - META.seaLevel) * 4200);
  const celsius = Math.round(-12 + t * 40);
  nameEl.textContent = biome;
  if (biome === "lake") {
    valsEl.textContent = `(${cx}, ${cy}) · fresh water · ${meters} m`;
  } else if (biome === "ocean" || biome === "shallows") {
    valsEl.textContent = `(${cx}, ${cy}) · open water · ${Math.max(0, -meters)} m deep`;
  } else {
    valsEl.textContent =
      `(${cx}, ${cy}) · ${meters} m · ${celsius}°C · rainfall ${(m * 100).toFixed(0)}%`;
  }
}

// --- gazetteer: click a town to fly to it ---
document.getElementById("gazetteer").addEventListener("click", (ev) => {
  const row = ev.target.closest(".town");
  if (!row) return;
  const x = +row.dataset.x, y = +row.dataset.y, w = Math.min(W, 40);
  vb = { x: x - w / 2, y: y - w / 2 * (H / W), w: w, h: w * (H / W) };
  applyVB();
});
applyVB();
</script>
</body>
</html>
"""
