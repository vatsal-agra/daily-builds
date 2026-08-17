"""The bundled end-to-end demo: exercises every shipped feature against real
input, asserts on the actual output (not just "did it run without an
exception"), and writes real artifacts to `outdir` -- SVG renders, an
interactive inspector page, and an index gallery linking them. Run via
`python3 cli.py demo` (or directly: `python3 -m folio.demo`).

This is Phase 5's verification script: every required and stretch feature
gets a concrete fixture and a concrete assertion here, matching what the
test suite covers but as one narrated, runnable walkthrough.
"""

import os
import sys

from .html_parser import parse_html
from .cascade import compute_style_tree
from .layout import layout_subtree
from .dom import pick_layout_root, find_element
from .paint import paint_svg, page_height


class DemoFailure(Exception):
    pass


def _check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("  [%s] %s%s" % (status, label, (" -- " + detail) if detail and not condition else ""))
    if not condition:
        raise DemoFailure(label + (": " + detail if detail else ""))


def _render(name, html, width, outdir):
    doc = parse_html(html)
    styles = compute_style_tree(doc, [])
    root_el = pick_layout_root(doc)
    root_box = layout_subtree(root_el, styles, width)
    height = page_height(root_box)
    svg = paint_svg(root_box, width, max(height, 10))
    path = os.path.join(outdir, name + ".svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return doc, styles, root_box, svg, path


def run(outdir):
    os.makedirs(outdir, exist_ok=True)
    gallery = []

    print("Folio demo -- exercising every shipped feature against real input\n")

    # -----------------------------------------------------------------
    print("1. HTML parser: tag soup, void elements, entities, comments")
    doc = parse_html(
        "<!DOCTYPE html><html><body>"
        "<ul><li>a<li>b<li>c</ul>"
        "<p>Tom &amp; Jerry &lt;3 &#65;&#x42;<br>line two</p>"
        "<!-- a comment --><div class=unquoted id='y'>ok</div>"
        "</body></html>"
    )
    lis = [n for n in doc.iter_element_descendants() if n.tag == "li"]
    p = find_element(doc, "p")
    text = "".join(c.data for c in p.children if c.is_text)
    _check("implicit </li> closing produces 3 sibling <li>s", len(lis) == 3, "got %d" % len(lis))
    _check("entity decoding", text.startswith("Tom & Jerry <3 AB"), repr(text))
    div = find_element(doc, "div")
    _check("unquoted attribute value parsed", div.get_attr("class") == "unquoted")

    # -----------------------------------------------------------------
    print("\n2. CSS cascade: specificity, !important, inheritance, UA defaults")
    css_html = (
        '<html><head><style>#x{color:red} .a{color:blue!important} '
        "h1{font-weight:bold}</style></head>"
        '<body><div id="x" class="a">t</div><h1>Title</h1></body></html>'
    )
    doc2 = parse_html(css_html)
    styles2 = compute_style_tree(doc2, [])
    d = find_element(doc2, "div")
    h1 = find_element(doc2, "h1")
    _check("!important beats a higher-specificity id selector", styles2[d]["color"][:3] == (0, 0, 255))
    _check("UA stylesheet gives h1 a real font-size default", styles2[h1]["font-size"] == 32.0)

    # -----------------------------------------------------------------
    print("\n3. Block layout: box model + margin collapsing, verified shape")
    layout_html = (
        "<html><body style='margin:0'>"
        "<div style='margin-bottom:20px;height:10px'>a</div>"
        "<div style='margin-top:30px;height:10px'>b</div>"
        "<div style='width:200px;margin:0 auto;height:10px' id='centered'>c</div>"
        "</body></html>"
    )
    doc3, styles3, root3, svg3, path3 = _render("layout_demo", layout_html, 600, outdir)
    gallery.append(("Block layout: margin collapsing + auto-margin centering", "layout_demo.svg"))
    body_box = root3
    second_div = body_box.block_children[1]
    first_div = body_box.block_children[0]
    third_div = body_box.block_children[2]
    gap = second_div.border_box_top - (first_div.border_box_top + first_div.border_box_height)
    _check("sibling margins collapse to max(20,30)=30, not sum=50", abs(gap - 30.0) < 0.5, "gap=%.1f" % gap)
    _check(
        "auto margins center a fixed-width box",
        abs(third_div.border_box_x - (600 - 200) / 2.0) < 0.5,
    )

    # -----------------------------------------------------------------
    print("\n4. Inline layout: greedy line-breaking + text-align")
    text_body = " ".join("word%d" % i for i in range(30))
    inline_html = (
        "<html><body style='margin:0'>"
        "<p style='width:200px;margin:0'>%s</p>"
        "<p style='width:200px;margin:0;text-align:right' id='r'>short</p>"
        "</body></html>" % text_body
    )
    doc4, styles4, root4, svg4, path4 = _render("inline_demo", inline_html, 400, outdir)
    gallery.append(("Inline layout: word-wrap + text-align", "inline_demo.svg"))
    p1 = root4.block_children[0]
    p2 = root4.block_children[1]
    _check("long text wraps across multiple lines", len(p1.lines) > 1, "%d lines" % len(p1.lines))
    right_line = p2.lines[0]
    frag_x, frag_text, frag_style, frag_w = right_line.fragments[-1]
    _check(
        "text-align:right flushes text to the content edge",
        abs((frag_x + frag_w) - (p2.border_box_x + p2.content_width)) < 0.5,
    )

    # -----------------------------------------------------------------
    print("\n5. Float layout (stretch): text wraps around a float, then clears it")
    float_text = " ".join("w%d" % i for i in range(30))
    float_html = (
        "<html><body style='margin:0'><div style='width:300px'>"
        "<div style='float:left;width:100px;height:40px'>img</div>"
        "<p style='margin:0'>%s</p>"
        "</div></body></html>" % float_text
    )
    doc5, styles5, root5, svg5, path5 = _render("float_demo", float_html, 300, outdir)
    gallery.append(("Float layout: text wraps around a float, then clears it", "float_demo.svg"))
    outer = root5.block_children[0]
    float_box = outer.block_children[0]
    para = outer.block_children[1]
    narrowed = [l for l in para.lines if l.y < float_box.border_box_height]
    widened = [l for l in para.lines if l.y >= float_box.border_box_height]
    _check("float is placed at the container's left edge", float_box.border_box_x == 0.0)
    _check("some lines narrow around the float", bool(narrowed) and narrowed[0].avail_width < 300)
    _check("lines below the float regain full width", bool(widened) and abs(widened[0].avail_width - 300) < 0.5)

    # -----------------------------------------------------------------
    print("\n6. Interactive inspector (stretch): self-contained HTML with hit-rects")
    from . import inspector

    inspector_src = os.path.join(outdir, "inspector_source.html")
    with open(inspector_src, "w", encoding="utf-8") as f:
        f.write(layout_html)
    inspector_out = os.path.join(outdir, "inspector.html")
    inspector.build(inspector_src, [], 600, inspector_out, use_oracle=False)
    with open(inspector_out, encoding="utf-8") as f:
        inspector_content = f.read()
    _check("inspector page is self-contained (embeds its own SVG + box data)", "folio-hit" in inspector_content and "BOXES = " in inspector_content)
    gallery.append(("Interactive box-model inspector", "inspector.html"))

    # -----------------------------------------------------------------
    print("\n7. Robustness: malformed/adversarial input does not crash")
    for bad in ("", "<div", "<div>" * 500 + "x" + "</div>" * 500, "<p>&amp"):
        d = parse_html(bad)  # must never raise
    _check("tag-soup / truncated / deeply-nested input all parse without raising", True)

    _write_gallery(outdir, gallery)
    print("\nAll checks passed. Artifacts written to %s/ (see index.html)." % outdir)
    return 0


def _write_gallery(outdir, gallery):
    rows = []
    for title, filename in gallery:
        if filename.endswith(".svg"):
            rows.append(
                "<section><h2>%s</h2><object type=\"image/svg+xml\" data=\"%s\"></object></section>"
                % (title, filename)
            )
        else:
            rows.append('<section><h2>%s</h2><p><a href="%s">%s</a></p></section>' % (title, filename, filename))
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Folio demo gallery</title>
<style>
body{font-family:-apple-system,sans-serif;background:#1e1f22;color:#e3e3e3;margin:0;padding:24px}
h1{font-weight:600} section{margin-bottom:32px} object{max-width:100%%;border:1px solid #3a3d41;background:#fff}
a{color:#4da3ff}
</style></head><body><h1>Folio demo gallery</h1>%s</body></html>""" % "".join(rows)
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "demo_out"))
