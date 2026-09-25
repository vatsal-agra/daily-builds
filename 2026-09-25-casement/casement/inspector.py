"""Generates a self-contained, interactive "DevTools-style" box-model
inspector: a single HTML file (Canvas-free, plain positioned <div>s +
vanilla JS, no build step, no dependencies) that shows the actual rendered
page and, on hover, the real margin/border/padding/content breakdown for
whichever box is under the cursor -- the same information a browser's own
"Computed" box-model panel shows, but for Casement's own layout.
"""

import base64
import json

from . import render as render_mod

_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Casement Inspector</title>
<style>
  :root {
    --bg: #1e1f22; --panel: #26282c; --border: #3a3d42; --text: #e6e6e6;
    --muted: #9aa0a6; --accent: #6cb6ff;
    --margin-color: #f0a15c; --border-color: #e8d44d; --padding-color: #7bc67e; --content-color: #6cb6ff;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font-family: 'SFMono-Regular', Consolas, Menlo, monospace; }
  header { padding: 10px 16px; border-bottom: 1px solid var(--border); font-size: 14px; display: flex; align-items: center; gap: 10px; }
  header .title { font-weight: bold; color: var(--accent); }
  header .hint { color: var(--muted); font-size: 12px; }
  .layout { display: flex; height: calc(100vh - 41px); }
  .stage-wrap { flex: 1; overflow: auto; padding: 20px; }
  .stage { position: relative; display: inline-block; background: #fff; box-shadow: 0 0 0 1px var(--border); }
  .stage img { display: block; }
  .overlay-box { position: absolute; pointer-events: none; box-sizing: border-box; }
  .ov-margin { border: 1px dashed var(--margin-color); background: rgba(240,161,92,0.12); }
  .ov-border { border: 1px dashed var(--border-color); background: rgba(232,212,77,0.12); }
  .ov-padding { border: 1px dashed var(--padding-color); background: rgba(123,198,126,0.15); }
  .ov-content { border: 1px solid var(--content-color); background: rgba(108,182,255,0.25); }
  .panel { width: 320px; border-left: 1px solid var(--border); background: var(--panel); padding: 16px; overflow: auto; }
  .panel h2 { margin: 0 0 4px; font-size: 15px; }
  .panel .elpath { color: var(--muted); font-size: 12px; margin-bottom: 16px; word-break: break-all; }
  .diagram { position: relative; margin: 0 auto 20px; width: 260px; }
  .layer { position: relative; display: flex; align-items: center; justify-content: center; border-radius: 2px; }
  .layer.margin { background: rgba(240,161,92,0.25); padding: 26px; }
  .layer.border { background: rgba(232,212,77,0.3); padding: 18px; }
  .layer.padding { background: rgba(123,198,126,0.3); padding: 18px; }
  .layer.content { background: rgba(108,182,255,0.45); min-width: 64px; min-height: 34px; font-size: 12px; color: #08243d; font-weight: bold; }
  .lab { position: absolute; font-size: 10px; color: #1b1b1b; background: rgba(255,255,255,0.6); border-radius: 2px; padding: 0 3px; line-height: 1.4; }
  .lab.top { top: 1px; left: 50%; transform: translateX(-50%); }
  .lab.bottom { bottom: 1px; left: 50%; transform: translateX(-50%); }
  .lab.left { left: 2px; top: 50%; transform: translateY(-50%); }
  .lab.right { right: 2px; top: 50%; transform: translateY(-50%); }
  .layer-name { position: absolute; top: -14px; left: 0; font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
  table.props { width: 100%; border-collapse: collapse; font-size: 12px; }
  table.props td { padding: 3px 4px; border-bottom: 1px solid var(--border); }
  table.props td:first-child { color: var(--muted); width: 40%; }
  .empty { color: var(--muted); font-size: 13px; padding: 8px 0; }
</style>
</head>
<body>
<header>
  <span class="title">Casement Inspector</span>
  <span class="hint">hover the page to inspect a box &middot; __BOX_COUNT__ boxes on this page</span>
</header>
<div class="layout">
  <div class="stage-wrap">
    <div class="stage" id="stage">
      <img id="page-img" src="data:image/png;base64,__PNG_B64__" width="__WIDTH__" height="__HEIGHT__">
    </div>
  </div>
  <div class="panel" id="panel">
    <div class="empty">Hover an element to see its box model.</div>
  </div>
</div>
<script id="boxes-data" type="application/json">__BOXES_JSON__</script>
<script>
(function () {
  var boxes = JSON.parse(document.getElementById('boxes-data').textContent);
  var stage = document.getElementById('stage');
  var panel = document.getElementById('panel');
  var overlays = [];

  function makeOverlay(cls) {
    var d = document.createElement('div');
    d.className = 'overlay-box ' + cls;
    stage.appendChild(d);
    return d;
  }
  var ovMargin = makeOverlay('ov-margin');
  var ovBorder = makeOverlay('ov-border');
  var ovPadding = makeOverlay('ov-padding');
  var ovContent = makeOverlay('ov-content');
  overlays = [ovMargin, ovBorder, ovPadding, ovContent];

  function place(el, rect) {
    el.style.left = rect.x + 'px';
    el.style.top = rect.y + 'px';
    el.style.width = Math.max(0, rect.w) + 'px';
    el.style.height = Math.max(0, rect.h) + 'px';
    el.style.display = 'block';
  }

  function hide() {
    overlays.forEach(function (o) { o.style.display = 'none'; });
  }

  function area(box) {
    var m = box.dims.margin_box;
    return Math.max(0, m.w) * Math.max(0, m.h);
  }

  function hitTest(x, y) {
    // Smallest containing box wins (innermost-first, like DevTools) --
    // but prefer a real element over the anonymous wrapper box its own
    // text run lives in, since "anonymous-block" means nothing to a user
    // looking for the element they hovered.
    var bestReal = null, bestAny = null;
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i];
      var m = b.dims.margin_box;
      if (x >= m.x && x <= m.x + m.w && y >= m.y && y <= m.y + m.h) {
        if (bestAny === null || area(b) < area(bestAny)) bestAny = b;
        if (b.box_type !== 'anonymous-block' && (bestReal === null || area(b) < area(bestReal))) bestReal = b;
      }
    }
    return bestReal || bestAny;
  }

  function fmt(n) { return (Math.round(n * 10) / 10).toString(); }

  function renderPanel(box) {
    var d = box.dims;
    var name = box.tag || box.box_type;
    if (box.id) name += '#' + box.id;
    (box.classes || []).forEach(function (c) { name += '.' + c; });

    var html = '';
    html += '<h2>&lt;' + (box.tag || box.box_type) + '&gt;</h2>';
    html += '<div class="elpath">' + name + '</div>';
    html += '<div class="diagram">';
    html += '  <div class="layer margin"><span class="layer-name">margin</span>';
    html += '    <span class="lab top">' + fmt(d.margin.top) + '</span>';
    html += '    <span class="lab right">' + fmt(d.margin.right) + '</span>';
    html += '    <span class="lab bottom">' + fmt(d.margin.bottom) + '</span>';
    html += '    <span class="lab left">' + fmt(d.margin.left) + '</span>';
    html += '    <div class="layer border"><span class="layer-name">border</span>';
    html += '      <span class="lab top">' + fmt(d.border.top) + '</span>';
    html += '      <span class="lab right">' + fmt(d.border.right) + '</span>';
    html += '      <span class="lab bottom">' + fmt(d.border.bottom) + '</span>';
    html += '      <span class="lab left">' + fmt(d.border.left) + '</span>';
    html += '      <div class="layer padding"><span class="layer-name">padding</span>';
    html += '        <span class="lab top">' + fmt(d.padding.top) + '</span>';
    html += '        <span class="lab right">' + fmt(d.padding.right) + '</span>';
    html += '        <span class="lab bottom">' + fmt(d.padding.bottom) + '</span>';
    html += '        <span class="lab left">' + fmt(d.padding.left) + '</span>';
    html += '        <div class="layer content">' + fmt(d.content.w) + ' &times; ' + fmt(d.content.h) + '</div>';
    html += '      </div></div></div>';
    html += '</div>';
    html += '<table class="props">';
    html += '<tr><td>box type</td><td>' + box.box_type + '</td></tr>';
    html += '<tr><td>content</td><td>' + fmt(d.content.w) + ' &times; ' + fmt(d.content.h) + ' @ (' + fmt(d.content.x) + ', ' + fmt(d.content.y) + ')</td></tr>';
    html += '<tr><td>border box</td><td>' + fmt(d.border_box.w) + ' &times; ' + fmt(d.border_box.h) + '</td></tr>';
    html += '<tr><td>margin box</td><td>' + fmt(d.margin_box.w) + ' &times; ' + fmt(d.margin_box.h) + '</td></tr>';
    html += '</table>';
    panel.innerHTML = html;
  }

  stage.addEventListener('mousemove', function (ev) {
    var rect = stage.getBoundingClientRect();
    var x = ev.clientX - rect.left;
    var y = ev.clientY - rect.top;
    var box = hitTest(x, y);
    if (!box) { hide(); return; }
    place(ovMargin, box.dims.margin_box);
    place(ovBorder, box.dims.border_box);
    var p = box.dims.padding, c = box.dims.content;
    place(ovPadding, { x: c.x - p.left, y: c.y - p.top, w: c.w + p.left + p.right, h: c.h + p.top + p.bottom });
    place(ovContent, c);
    renderPanel(box);
  });
  stage.addEventListener('mouseleave', hide);
})();
</script>
</body>
</html>
"""


def generate_inspector_html(html_text, extra_css="", viewport_width=800):
    result = render_mod.render(html_text, extra_css=extra_css, viewport_width=viewport_width)
    boxes = render_mod.export_flat_boxes(result.root_box)
    png_b64 = base64.b64encode(result.png_bytes).decode("ascii")
    html = _TEMPLATE
    html = html.replace("__BOX_COUNT__", str(len(boxes)))
    html = html.replace("__PNG_B64__", png_b64)
    html = html.replace("__WIDTH__", str(result.width))
    html = html.replace("__HEIGHT__", str(result.height))
    html = html.replace("__BOXES_JSON__", json.dumps(boxes))
    return html
