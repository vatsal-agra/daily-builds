"""Generates a self-contained, interactive "DevTools-lite" box inspector:
every box Cascade computed, rendered as real positioned HTML/CSS (so it
visually matches the page) with a click-to-inspect side panel showing the
box-model breakdown and computed style -- all driven by one real Cascade
layout run. The browser holds zero layout logic of its own, same
precompute-then-render pattern this repo has used since Gambit/Formulate.
"""

import html as _html
import json

from dom import Element

_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Cascade Inspector</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, sans-serif; background: #f6f7f9; display: flex; }
  #stage-wrap { flex: 1; overflow: auto; padding: 24px; }
  #stage { position: relative; background: #ffffff; box-shadow: 0 1px 4px rgba(0,0,0,.15);
           outline: 1px solid #ddd; }
  .box { position: absolute; box-sizing: border-box; cursor: pointer; }
  .box:hover { outline: 2px solid #4c8bf5; outline-offset: -1px; z-index: 1000; }
  .box.selected { outline: 2px solid #e0532c; outline-offset: -1px; z-index: 1001; }
  /* Cascade's own text layout assumes a fixed per-character advance width
     (see font.py's CHAR_WIDTH_RATIO) -- monospace is what makes these
     absolutely-positioned real-HTML-text words land where our own line-
     breaking algorithm computed them, without drifting into their
     neighbors the way a proportional font's real (narrower/wider) glyph
     metrics would. */
  .txt { position: absolute; white-space: pre; pointer-events: none;
         font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
  #panel { width: 320px; flex-shrink: 0; background: #1e2128; color: #e6e6e6; padding: 16px;
           font-family: ui-monospace, monospace; font-size: 12.5px; overflow-y: auto; }
  #panel h2 { font-size: 14px; margin: 0 0 4px; color: #7fc8ff; }
  #panel .hint { color: #888; }
  .kv { display: flex; justify-content: space-between; padding: 2px 0; border-bottom: 1px solid #2c3038; }
  .kv b { color: #ffcf7f; font-weight: normal; }
  .boxmodel { margin: 14px 0; }
  .bm-layer { border: 1px dashed #555; padding: 6px; text-align: center; font-size: 11px; }
  .bm-margin { background: #3a2f1e; color: #d9a441; }
  .bm-border { background: #33301e; color: #d9c441; }
  .bm-padding { background: #1e3324; color: #6fd98a; }
  .bm-content { background: #1e2a33; color: #6fc4d9; padding: 10px; }
</style></head>
<body>
  <div id="stage-wrap"><div id="stage" style="width:__WIDTH__px;height:__HEIGHT__px">__BOXES_HTML__</div></div>
  <div id="panel"><h2>CASCADE INSPECTOR</h2><div class="hint">Click any box to inspect it.</div>
  <div id="detail"></div></div>
<script>
const DATA = __DATA_JSON__;
let selected = null;
function fmt(n) { return Math.round(n * 10) / 10; }
function show(id) {
  const d = DATA[id];
  if (!d) return;
  if (selected) selected.classList.remove('selected');
  selected = document.querySelector('[data-id="' + id + '"]');
  if (selected) selected.classList.add('selected');
  const el = document.getElementById('detail');
  let rows = '';
  for (const [k, v] of Object.entries(d.style)) {
    rows += `<div class="kv"><span>${k}</span><b>${v}</b></div>`;
  }
  el.innerHTML = `
    <div class="kv"><span>tag</span><b>&lt;${d.tag}&gt;</b></div>
    <div class="kv"><span>box</span><b>${fmt(d.x)}, ${fmt(d.y)}</b></div>
    <div class="kv"><span>size</span><b>${fmt(d.width)} x ${fmt(d.height)}</b></div>
    <div class="boxmodel">
      <div class="bm-layer bm-margin">margin ${d.margin.join(' / ')}
        <div class="bm-layer bm-border">border ${d.border.join(' / ')}
          <div class="bm-layer bm-padding">padding ${d.padding.join(' / ')}
            <div class="bm-content">${fmt(d.contentWidth)} x ${fmt(d.contentHeight)}</div>
          </div>
        </div>
      </div>
    </div>
    <div class="hint">computed style</div>
    ${rows}`;
}
document.querySelectorAll('.box').forEach(b => {
  b.addEventListener('click', (e) => { e.stopPropagation(); show(b.dataset.id); });
});
</script>
</body></html>
"""

_STYLE_KEYS = ["display", "color", "background-color", "font-size", "font-weight",
               "text-align", "width", "height"]


def _rgba_css(c):
    r, g, b, a = c
    return f"rgba({r},{g},{b},{a / 255.0:.2f})"


def generate_inspector_html(root, viewport_width):
    boxes_html = []
    data = {}
    counter = [0]

    def visit(box):
        if box.box_type == "text" and box.text:
            boxes_html.append(
                f'<div class="txt" style="left:{box.x:.1f}px;top:{box.y:.1f}px;'
                f'font-size:{box.font_size:.1f}px;font-weight:{box.font_weight};'
                f'color:{_rgba_css(box.color)}">{_html.escape(box.text)}</div>')
        if isinstance(box.node, Element):
            bid = f"b{counter[0]}"
            counter[0] += 1
            bg = _rgba_css(box.background_color)
            border_css = ""
            b = box.border
            bc = box.border_color
            if b.top:
                border_css += f"border-top:{b.top:.1f}px solid {_rgba_css(bc.top)};"
            if b.right:
                border_css += f"border-right:{b.right:.1f}px solid {_rgba_css(bc.right)};"
            if b.bottom:
                border_css += f"border-bottom:{b.bottom:.1f}px solid {_rgba_css(bc.bottom)};"
            if b.left:
                border_css += f"border-left:{b.left:.1f}px solid {_rgba_css(bc.left)};"
            boxes_html.append(
                f'<div class="box" data-id="{bid}" style="left:{box.x:.1f}px;top:{box.y:.1f}px;'
                f'width:{box.width:.1f}px;height:{box.height:.1f}px;background:{bg};{border_css}">'
                f'</div>')
            style_subset = {k: box.style.get(k, "") for k in _STYLE_KEYS if box.style.get(k)}
            data[bid] = {
                "tag": box.node.tag, "x": box.x, "y": box.y,
                "width": box.width, "height": box.height,
                "contentWidth": box.content_width, "contentHeight": box.content_height,
                "margin": [round(box.margin.top, 1), round(box.margin.right, 1),
                           round(box.margin.bottom, 1), round(box.margin.left, 1)],
                "border": [round(b.top, 1), round(b.right, 1), round(b.bottom, 1), round(b.left, 1)],
                "padding": [round(box.padding.top, 1), round(box.padding.right, 1),
                            round(box.padding.bottom, 1), round(box.padding.left, 1)],
                "style": style_subset,
            }
        for c in box.children:
            visit(c)

    visit(root)
    out = _TEMPLATE
    out = out.replace("__WIDTH__", str(int(viewport_width)))
    out = out.replace("__HEIGHT__", str(int(root.height) + 2))
    out = out.replace("__BOXES_HTML__", "".join(boxes_html))
    out = out.replace("__DATA_JSON__", json.dumps(data))
    return out
