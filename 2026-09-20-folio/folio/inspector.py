"""Builds the interactive DOM/box-model inspector: a single self-contained
HTML/Canvas/vanilla-JS page. Folio computes every pixel and every piece of
layout data ahead of time and embeds it as inline JSON; the browser only
paints exactly what it's told and does simple point-in-rect hit testing on
click -- no client-side HTML/CSS/layout logic of any kind, the same
"engine computes, browser only paints" architecture this repo's other
server- or data-backed visualizers (Gambit, Formulate, Torque, Beacon) use.
"""

import json

from .dom import Element, Text
from .layout import Box, InlineBox, TextRun, char_width, line_height_px, parse_length
from .paint import parse_color

_DISPLAYED_PROPS = [
    "display", "color", "background-color", "font-size", "font-weight",
    "font-style", "text-align", "text-decoration", "width", "height",
    "box-sizing", "float", "clear",
]


def _dom_path(element):
    parts = []
    node = element
    while isinstance(node, Element):
        label = node.tag
        if node.id:
            label += f"#{node.id}"
        for c in node.classes:
            label += f".{c}"
        parts.append(label)
        node = node.parent
    return " > ".join(reversed(parts))


def _style_summary(style):
    if style is None:
        return {}
    return {p: style.get(p) for p in _DISPLAYED_PROPS}


def _nearest_element(node):
    while node is not None and not isinstance(node, Element):
        node = getattr(node, "parent", None)
    return node


def _font_size_of(style):
    if style is None:
        return 16
    size = parse_length(style.get("font-size"), None)
    return size if isinstance(size, int) and size > 0 else 16


def _collect_regions(root_box):
    regions = []

    def visit(box):
        if isinstance(box, Box):
            if box.node is not None and isinstance(box.node, Element):
                regions.append({
                    "kind": "block",
                    "tag": box.node.tag,
                    "domPath": _dom_path(box.node),
                    "x": box.x, "y": box.y, "width": box.width, "height": box.height,
                    "margin": box.margin, "border": box.border, "padding": box.padding,
                    "style": _style_summary(box.style),
                })
            for child in box.children:
                visit(child)
        elif isinstance(box, TextRun):
            el = _nearest_element(box.node)
            if el is not None:
                regions.append({
                    "kind": "text",
                    "tag": el.tag,
                    "domPath": _dom_path(el),
                    "x": box.x, "y": box.y, "width": box.width, "height": box.height,
                    "text": box.text,
                    "style": _style_summary(box.style),
                })
        elif isinstance(box, InlineBox):
            el = _nearest_element(box.node)
            if el is not None:
                regions.append({
                    "kind": "text",
                    "tag": el.tag,
                    "domPath": _dom_path(el),
                    "x": box.x, "y": box.y, "width": box.width, "height": box.height,
                    "text": f"<{el.tag}>",
                    "style": _style_summary(box.style),
                })

    visit(root_box)
    return regions


def _paint_to_json(paint_commands):
    out = []
    for cmd in paint_commands:
        entry = {
            "kind": cmd.kind,
            "x": cmd.x, "y": cmd.y, "width": cmd.width, "height": cmd.height,
            "color": list(cmd.color) if cmd.color else None,
        }
        if cmd.kind == "text":
            entry["text"] = cmd.extra.get("text", "")
            entry["bold"] = bool(cmd.extra.get("bold"))
            entry["italic"] = bool(cmd.extra.get("italic"))
            entry["underline"] = bool(cmd.extra.get("underline"))
            entry["fontSize"] = _font_size_of(cmd.box.style if hasattr(cmd.box, "style") else None)
        out.append(entry)
    return out


def render_inspector_html(page):
    data = {
        "width": page.viewport_width,
        "height": max(1, page.height),
        "paint": _paint_to_json(page.paint_commands),
        "regions": _collect_regions(page.root_box),
        "charWidthRatio": 0.6,
        "lineHeightRatio": 1.2,
    }
    data_json = json.dumps(data)
    return _TEMPLATE.replace("__FOLIO_DATA__", data_json)


_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Folio Inspector</title>
<style>
  :root {
    --bg: #1e1f22; --panel: #2b2d31; --border: #3f4147; --text: #d7dadc;
    --muted: #9aa0a6; --accent: #4fc3f7; --margin: #f7b26a; --border-c: #f7e26a;
    --padding: #a4d97b; --content: #6fb3f2;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 13px;
  }
  #layout { display: flex; height: 100vh; }
  #canvas-wrap {
    flex: 1 1 auto; overflow: auto; padding: 24px; background:
      repeating-conic-gradient(#26282c 0% 25%, #1e1f22 0% 50%) 50% / 20px 20px;
  }
  #stage { position: relative; display: inline-block; }
  canvas { display: block; background: #fff; box-shadow: 0 4px 24px rgba(0,0,0,.4); cursor: crosshair; }
  #panel {
    width: 340px; flex: 0 0 340px; border-left: 1px solid var(--border);
    background: var(--panel); overflow-y: auto; padding: 16px;
  }
  #panel h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .08em;
    color: var(--muted); margin: 0 0 8px; }
  #domPath { word-break: break-all; color: var(--accent); margin-bottom: 16px; line-height: 1.5; }
  .empty { color: var(--muted); font-style: italic; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
  td { padding: 2px 4px; border-bottom: 1px solid var(--border); vertical-align: top; }
  td.k { color: var(--muted); width: 42%; }
  td.v { color: var(--text); font-weight: 600; }
  #boxmodel { margin: 8px 0 20px; }
  .bm-layer { position: relative; margin: 0 auto; text-align: center; }
  .bm-margin { background: var(--margin); }
  .bm-border { background: var(--border-c); }
  .bm-padding { background: var(--padding); }
  .bm-content { background: var(--content); color: #10202b; font-weight: 700;
    display: flex; align-items: center; justify-content: center; min-height: 34px; min-width: 64px; }
  .bm-label { position: absolute; font-size: 10px; color: #10202b; opacity: .85; }
  .bm-label.top { top: 2px; left: 50%; transform: translateX(-50%); }
  .bm-label.bottom { bottom: 2px; left: 50%; transform: translateX(-50%); }
  .bm-label.left { left: 4px; top: 50%; transform: translateY(-50%); }
  .bm-label.right { right: 4px; top: 50%; transform: translateY(-50%); }
  .bm-pad { padding: 18px; }
  .legend { display: flex; gap: 10px; flex-wrap: wrap; font-size: 11px; color: var(--muted); margin-bottom: 10px; }
  .legend span { display: inline-flex; align-items: center; gap: 4px; }
  .swatch { width: 10px; height: 10px; display: inline-block; border-radius: 2px; }
  #hint { color: var(--muted); font-size: 12px; margin-top: 4px; }
</style>
</head>
<body>
<div id="layout">
  <div id="canvas-wrap">
    <div id="stage">
      <canvas id="canvas"></canvas>
    </div>
  </div>
  <div id="panel">
    <h2>Folio Inspector</h2>
    <div id="hint">Click any rendered element to inspect it -- the same
    layout tree Folio's PNG renderer painted from.</div>
    <div id="domPath" class="empty">Nothing selected yet.</div>
    <div id="boxmodel"></div>
    <h2>Computed style</h2>
    <table id="styleTable"><tr><td class="empty">--</td></tr></table>
  </div>
</div>
<script>
const DATA = __FOLIO_DATA__;

const canvas = document.getElementById('canvas');
canvas.width = DATA.width;
canvas.height = DATA.height;
const ctx = canvas.getContext('2d');

function charWidth(fontSize) { return Math.max(1, Math.round(fontSize * DATA.charWidthRatio)); }
function lineHeight(fontSize) { return Math.max(1, Math.round(fontSize * DATA.lineHeightRatio)); }

function rgb(c) { return c ? `rgb(${c[0]},${c[1]},${c[2]})` : 'transparent'; }

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (const cmd of DATA.paint) {
    if (cmd.kind === 'rect') {
      if (!cmd.color) continue;
      ctx.fillStyle = rgb(cmd.color);
      ctx.fillRect(cmd.x, cmd.y, cmd.width, cmd.height);
    } else if (cmd.kind === 'text') {
      const size = cmd.fontSize || 16;
      let font = `${size}px monospace`;
      if (cmd.bold) font = 'bold ' + font;
      if (cmd.italic) font = 'italic ' + font;
      ctx.font = font;
      ctx.fillStyle = rgb(cmd.color) || '#000';
      ctx.textBaseline = 'top';
      ctx.fillText(cmd.text, cmd.x, cmd.y);
      if (cmd.underline) {
        const w = charWidth(size) * cmd.text.length;
        const uy = cmd.y + lineHeight(size) - 2;
        ctx.strokeStyle = rgb(cmd.color) || '#000';
        ctx.beginPath();
        ctx.moveTo(cmd.x, uy);
        ctx.lineTo(cmd.x + w, uy);
        ctx.stroke();
      }
    }
  }
  if (selected) drawHighlight(selected);
}

let selected = null;

function drawHighlight(region) {
  ctx.save();
  ctx.strokeStyle = '#4fc3f7';
  ctx.lineWidth = 2;
  ctx.strokeRect(region.x + 1, region.y + 1, Math.max(0, region.width - 2), Math.max(0, region.height - 2));
  if (region.margin) {
    ctx.fillStyle = 'rgba(247,178,106,0.35)';
    const m = region.margin;
    ctx.fillRect(region.x - m.left, region.y - m.top, region.width + m.left + m.right, m.top);
    ctx.fillRect(region.x - m.left, region.y + region.height, region.width + m.left + m.right, m.bottom);
    ctx.fillRect(region.x - m.left, region.y, m.left, region.height);
    ctx.fillRect(region.x + region.width, region.y, m.right, region.height);
  }
  ctx.restore();
}

function hitTest(px, py) {
  for (let i = DATA.regions.length - 1; i >= 0; i--) {
    const r = DATA.regions[i];
    if (px >= r.x && px <= r.x + r.width && py >= r.y && py <= r.y + r.height) {
      return r;
    }
  }
  return null;
}

canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const px = (e.clientX - rect.left) * scaleX;
  const py = (e.clientY - rect.top) * scaleY;
  const hit = hitTest(px, py);
  selected = hit;
  draw();
  renderPanel(hit);
});

function renderPanel(region) {
  const pathEl = document.getElementById('domPath');
  const bmEl = document.getElementById('boxmodel');
  const styleTable = document.getElementById('styleTable');
  if (!region) {
    pathEl.textContent = 'Nothing selected yet.';
    pathEl.className = 'empty';
    bmEl.innerHTML = '';
    styleTable.innerHTML = '<tr><td class="empty">--</td></tr>';
    return;
  }
  pathEl.textContent = region.domPath + (region.kind === 'text' ? '  (text)' : '');
  pathEl.className = '';

  if (region.kind === 'block' && region.margin) {
    const m = region.margin, b = region.border, p = region.padding;
    bmEl.innerHTML = `
      <div class="legend">
        <span><i class="swatch" style="background:var(--margin)"></i>margin</span>
        <span><i class="swatch" style="background:var(--border-c)"></i>border</span>
        <span><i class="swatch" style="background:var(--padding)"></i>padding</span>
        <span><i class="swatch" style="background:var(--content)"></i>content</span>
      </div>
      <div class="bm-layer bm-margin bm-pad">
        <span class="bm-label top">${m.top}</span>
        <span class="bm-label bottom">${m.bottom}</span>
        <span class="bm-label left">${m.left}</span>
        <span class="bm-label right">${m.right}</span>
        <div class="bm-layer bm-border bm-pad">
          <span class="bm-label top">${b.top}</span>
          <span class="bm-label bottom">${b.bottom}</span>
          <span class="bm-label left">${b.left}</span>
          <span class="bm-label right">${b.right}</span>
          <div class="bm-layer bm-padding bm-pad">
            <span class="bm-label top">${p.top}</span>
            <span class="bm-label bottom">${p.bottom}</span>
            <span class="bm-label left">${p.left}</span>
            <span class="bm-label right">${p.right}</span>
            <div class="bm-content">${region.width - b.left - b.right - p.left - p.right} &times; ${region.height - b.top - b.bottom - p.top - p.bottom}</div>
          </div>
        </div>
      </div>`;
  } else {
    bmEl.innerHTML = `<div class="empty">Text run: ${region.width}&times;${region.height}px${
      region.text ? ' -- "' + region.text.replace(/</g, '&lt;') + '"' : ''}</div>`;
  }

  const rows = Object.entries(region.style || {}).map(
    ([k, v]) => `<tr><td class="k">${k}</td><td class="v">${v}</td></tr>`
  ).join('');
  styleTable.innerHTML = rows || '<tr><td class="empty">--</td></tr>';
}

draw();
renderPanel(null);
</script>
</body>
</html>
"""
