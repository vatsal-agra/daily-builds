"""The interactive box-model inspector -- Folio's second stretch feature.

Renders a page the same way `paint.py` does, but with an invisible
click-target rect layered over every box, and ships a self-contained HTML
viewer (no CDN, no build step, no framework) that behaves like a small
slice of real browser DevTools: click any element in the rendered page and
see its nested content/padding/border/margin box-model diagram plus its
resolved computed style, redrawn from Folio's own geometry -- not a canned
screenshot.

If Playwright is available, it also renders the *same* fixture in real
headless Chromium and reports Folio-vs-Chromium pixel deltas for every
element carrying a `data-t` attribute, right in the page -- the same
oracle the test suite uses, made visible.
"""

import html as _html_escape_module
import json

from .cascade import compute_style_tree
from .html_parser import parse_html
from .dom import pick_layout_root
from .layout import layout_subtree
from .paint import paint_svg, page_height
from .values import Length, color_to_css


def _esc(s):
    return _html_escape_module.escape(str(s), quote=True)


def _style_summary(style):
    if style is None:
        return {}
    out = {}
    for prop in (
        "display", "position", "float", "clear", "color", "background-color",
        "font-size", "font-weight", "text-align", "width", "height",
    ):
        val = style.get(prop)
        if isinstance(val, Length):
            out[prop] = repr(val)
        elif isinstance(val, tuple) and len(val) == 4:
            out[prop] = color_to_css(val)
        else:
            out[prop] = val
    return out


def _collect_boxes(root_box, box_ids):
    """Assign a stable id to every box (recorded in `box_ids`, keyed by
    `id(box)` -- LayoutBox uses `__slots__` and has no spare field to stash
    an inspector-only id on) and return {id: box-info dict}."""
    boxes = {}
    counter = [0]

    def visit(box):
        box_id = counter[0]
        counter[0] += 1
        box_ids[id(box)] = box_id
        x, y, w, h = box.rect()
        tag = "anon" if box.is_anonymous else (box.element.tag if box.element else "#root")
        data_t = box.element.get_attr("data-t") if (box.element is not None) else None
        boxes[box_id] = {
            "id": box_id,
            "tag": tag,
            "data_t": data_t,
            "border_box": [x, y, w, h],
            "content_box": [
                x + box.border_left + box.padding_left,
                y + box.border_top + box.padding_top,
                box.content_width,
                box.content_height,
            ],
            "padding": [box.padding_top, box.padding_right, box.padding_bottom, box.padding_left],
            "border": [box.border_top, box.border_right, box.border_bottom, box.border_left],
            "margin": [box.margin_top, box.margin_right, box.margin_bottom, box.margin_left],
            "style": _style_summary(box.style if not box.is_anonymous else None),
        }
        for c in box.block_children:
            visit(c)

    visit(root_box)
    return boxes


def _paint_with_hit_rects(root_box, width, height, box_ids):
    """The normal SVG paint, plus a transparent, clickable rect over every
    box's border box, topmost box last (so nested boxes remain clickable
    even though an ancestor's rect physically covers the same area)."""
    svg = paint_svg(root_box, width, height)
    hit_rects = []

    def visit(box):
        x, y, w, h = box.rect()
        if w > 0 and h > 0:
            hit_rects.append(
                '<rect class="folio-hit" data-id="%d" x="%g" y="%g" width="%g" height="%g" '
                'fill="transparent" style="cursor:pointer"/>' % (box_ids[id(box)], x, y, w, h)
            )
        for c in box.block_children:
            visit(c)

    visit(root_box)
    return svg.replace("</svg>", "\n".join(hit_rects) + "\n</svg>")


def build(html_path, css_paths, width, output_path, use_oracle=True):
    with open(html_path, "r", encoding="utf-8") as f:
        html_text = f.read()
    extra_css = []
    for p in css_paths or []:
        with open(p, "r", encoding="utf-8") as f:
            extra_css.append(f.read())

    doc = parse_html(html_text)
    styles = compute_style_tree(doc, extra_css)
    root_el = pick_layout_root(doc)
    if root_el is None:
        raise ValueError("document has no elements to render")
    root_box = layout_subtree(root_el, styles, width)
    height = max(page_height(root_box), 10)

    box_ids = {}
    boxes = _collect_boxes(root_box, box_ids)
    svg = _paint_with_hit_rects(root_box, width, height, box_ids)

    oracle_rows = []
    if use_oracle:
        try:
            from tools import oracle as oracle_mod

            chromium_boxes = oracle_mod.chromium_boxes(html_text, viewport_width=int(width))
            by_data_t = {b["data_t"]: b for b in boxes.values() if b["data_t"]}
            for data_t, (cx, cy, cw, ch) in sorted(chromium_boxes.items()):
                info = by_data_t.get(data_t)
                if info is None:
                    continue
                fx, fy, fw, fh = info["border_box"]
                oracle_rows.append(
                    {
                        "data_t": data_t,
                        "folio": [fx, fy, fw, fh],
                        "chromium": [cx, cy, cw, ch],
                        "delta": [fx - cx, fy - cy, fw - cw, fh - ch],
                    }
                )
        except Exception:
            oracle_rows = None  # playwright unavailable or failed -- panel simply omitted
    else:
        oracle_rows = None

    page = _render_page(svg, width, height, boxes, oracle_rows)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page)
    return output_path


_PAGE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Folio Inspector</title>
<style>
  :root {
    --bg: #1e1f22; --panel: #26282b; --border: #3a3d41; --text: #e3e3e3;
    --muted: #9a9ea3; --accent: #4da3ff; --accent2: #ff8a4d; --mono: 'SF Mono', Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, Segoe UI, sans-serif; }
  #layout { display: flex; height: 100vh; }
  #canvas-wrap { flex: 1 1 auto; overflow: auto; padding: 24px; background:
    repeating-conic-gradient(#242527 0% 25%, #1e1f22 0% 50%) 50% / 20px 20px; }
  #canvas-wrap svg { background: #fff; box-shadow: 0 4px 24px rgba(0,0,0,.5); display: block; }
  .folio-hit:hover { fill: rgba(77,163,255,0.18) !important; }
  #side { width: 360px; flex: 0 0 360px; border-left: 1px solid var(--border);
    background: var(--panel); overflow-y: auto; padding: 16px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
    margin: 0 0 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .tag { font-family: var(--mono); color: var(--accent2); font-size: 15px; }
  #boxmodel { margin: 14px 0; }
  .bm-margin, .bm-border, .bm-padding, .bm-content {
    display: flex; align-items: center; justify-content: center; position: relative;
  }
  .bm-margin { background: rgba(246,178,107,.18); padding: 14px; }
  .bm-border { background: rgba(255,229,143,.18); padding: 10px; }
  .bm-padding { background: rgba(147,196,125,.18); padding: 10px; }
  .bm-content { background: rgba(111,168,220,.35); min-height: 34px; min-width: 60px;
    font-family: var(--mono); font-size: 12px; }
  .bm-label { position: absolute; font-size: 9px; color: var(--muted); font-family: var(--mono); }
  .bm-top { top: 1px; left: 50%; transform: translateX(-50%); }
  .bm-bottom { bottom: 1px; left: 50%; transform: translateX(-50%); }
  .bm-left { left: 3px; top: 50%; transform: translateY(-50%); }
  .bm-right { right: 3px; top: 50%; transform: translateY(-50%); }
  table.kv { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 12px; }
  table.kv td { padding: 3px 4px; border-bottom: 1px solid var(--border); }
  table.kv td:first-child { color: var(--muted); }
  #empty-hint { color: var(--muted); font-size: 13px; line-height: 1.5; }
  #oracle table { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 11px; margin-top: 8px; }
  #oracle td, #oracle th { padding: 4px 5px; border-bottom: 1px solid var(--border); text-align: right; }
  #oracle th { color: var(--muted); font-weight: normal; text-align: right; }
  #oracle td:first-child, #oracle th:first-child { text-align: left; }
  .ok { color: #7cd992; } .bad { color: #ff6b6b; }
  #meta { color: var(--muted); font-size: 11px; padding: 10px 16px; border-top: 1px solid var(--border); }
</style>
</head>
<body>
<div id="layout">
  <div id="canvas-wrap">__SVG__</div>
  <div id="side">
    <h2>Box model</h2>
    <div id="detail"><div id="empty-hint">Click any element in the rendered page to inspect its box model, computed style, and (if available) the Chromium oracle diff for its geometry.</div></div>
    __ORACLE__
  </div>
</div>
<div id="meta">Folio Inspector &middot; __WIDTH__&times;__HEIGHT__ viewport &middot; __COUNT__ boxes</div>
<script>
const BOXES = __BOXES_JSON__;

function fmt(n) { return (Math.round(n * 100) / 100).toString(); }

function renderBoxModel(b) {
  const [pt, pr, pb, pl] = b.padding, [bt, br, bb, bl] = b.border, [mt, mr, mb, ml] = b.margin;
  const [cx, cy, cw, ch] = b.content_box;
  return `
    <div class="bm-margin">
      <span class="bm-label bm-top">margin ${fmt(mt)}</span>
      <span class="bm-label bm-bottom">${fmt(mb)}</span>
      <span class="bm-label bm-left">${fmt(ml)}</span>
      <span class="bm-label bm-right">${fmt(mr)}</span>
      <div class="bm-border">
        <span class="bm-label bm-top">border ${fmt(bt)}</span>
        <span class="bm-label bm-bottom">${fmt(bb)}</span>
        <span class="bm-label bm-left">${fmt(bl)}</span>
        <span class="bm-label bm-right">${fmt(br)}</span>
        <div class="bm-padding">
          <span class="bm-label bm-top">padding ${fmt(pt)}</span>
          <span class="bm-label bm-bottom">${fmt(pb)}</span>
          <span class="bm-label bm-left">${fmt(pl)}</span>
          <span class="bm-label bm-right">${fmt(pr)}</span>
          <div class="bm-content">${fmt(cw)} &times; ${fmt(ch)}</div>
        </div>
      </div>
    </div>`;
}

function renderStyle(style) {
  const rows = Object.entries(style || {}).map(([k, v]) =>
    `<tr><td>${k}</td><td>${v === null || v === undefined ? '—' : v}</td></tr>`).join('');
  return `<table class="kv">${rows}</table>`;
}

document.querySelectorAll('.folio-hit').forEach(el => {
  el.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const id = el.getAttribute('data-id');
    const b = BOXES[id];
    document.getElementById('detail').innerHTML =
      `<div class="tag">&lt;${b.tag}&gt;</div>` +
      (b.data_t ? `<div style="color:var(--muted);font-size:11px">data-t="${b.data_t}"</div>` : '') +
      `<div id="boxmodel">${renderBoxModel(b)}</div>` +
      `<h2>Computed style</h2>${renderStyle(b.style)}`;
  });
});
</script>
</body>
</html>
"""


def _render_page(svg, width, height, boxes, oracle_rows):
    boxes_json = json.dumps(boxes)
    oracle_html = ""
    if oracle_rows is not None:
        if oracle_rows:
            body_rows = []
            for row in oracle_rows:
                dx, dy, dw, dh = row["delta"]
                worst = max(abs(dx), abs(dy), abs(dw), abs(dh))
                cls = "ok" if worst < 0.6 else "bad"
                body_rows.append(
                    "<tr class='%s'><td>%s</td><td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.1f</td></tr>"
                    % (cls, _esc(row["data_t"]), dx, dy, dw, dh)
                )
            oracle_html = (
                "<h2 style='margin-top:18px'>Chromium oracle (&Delta;px)</h2><div id='oracle'>"
                "<table><tr><th>data-t</th><th>&Delta;x</th><th>&Delta;y</th><th>&Delta;w</th><th>&Delta;h</th></tr>"
                + "".join(body_rows)
                + "</table></div>"
            )
        else:
            oracle_html = (
                "<h2 style='margin-top:18px'>Chromium oracle</h2>"
                "<div id='empty-hint'>No <code>data-t</code> attributes found in this fixture "
                "-- add them to elements to see a live Folio-vs-Chromium geometry diff here.</div>"
            )
    page = _PAGE_TEMPLATE
    page = page.replace("__SVG__", svg)
    page = page.replace("__WIDTH__", str(int(width)))
    page = page.replace("__HEIGHT__", str(round(height)))
    page = page.replace("__COUNT__", str(len(boxes)))
    page = page.replace("__BOXES_JSON__", boxes_json)
    page = page.replace("__ORACLE__", oracle_html)
    return page
