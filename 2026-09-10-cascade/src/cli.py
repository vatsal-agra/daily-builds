#!/usr/bin/env python3
"""Cascade CLI: render HTML+CSS pages through the from-scratch engine."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cascade import Cascade
from html_parser import parse_html
from layout import build_root
from paint import paint_tree


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_page(html_path, css_path=None):
    html_text = _read(html_path)
    doc = parse_html(html_text)
    css_text = ""
    if css_path:
        css_text = _read(css_path)
    else:
        # collect inline <style> tags
        from dom import find_all
        for style_el in find_all(doc, tag="style"):
            css_text += style_el.text_content() + "\n"
    cascade = Cascade(css_text)
    cascade.compute_styles(doc)
    html_el = doc.children[0]
    return doc, html_el


def cmd_render(args):
    doc, html_el = _load_page(args.html, args.css)
    root = build_root(html_el, args.width)
    canvas = paint_tree(root, args.width, viewport_height=max(root.height, args.width * 0.1))
    with open(args.out, "wb") as f:
        f.write(canvas.to_png_bytes())
    print(f"wrote {args.out} ({canvas.width}x{canvas.height})")


def cmd_layout(args):
    doc, html_el = _load_page(args.html, args.css)
    root = build_root(html_el, args.width)

    def dump(box, indent=0):
        tag = box.node.tag if hasattr(box.node, "tag") else ("anon" if box.anonymous else box.box_type)
        print("  " * indent + f"{box.box_type}:{tag} x={box.x:.1f} y={box.y:.1f} "
              f"w={box.width:.1f} h={box.height:.1f}")
        for c in box.children:
            dump(c, indent + 1)

    dump(root)


def cmd_boxes_json(args):
    """Emit a flat JSON list of {tag, x, y, width, height} for every
    element box -- used by the Chromium differential test harness."""
    doc, html_el = _load_page(args.html, args.css)
    root = build_root(html_el, args.width)
    from dom import Element
    out = []

    def walk(box):
        if isinstance(box.node, Element):
            out.append({"tag": box.node.tag, "id": box.node.id, "class": " ".join(box.node.classes),
                        "x": box.x, "y": box.y, "width": box.width, "height": box.height})
        for c in box.children:
            walk(c)

    walk(root)
    print(json.dumps(out, indent=2))


def cmd_demo(args):
    here = os.path.dirname(os.path.abspath(__file__))
    examples_dir = os.path.join(os.path.dirname(here), "examples")
    out_dir = os.path.join(os.path.dirname(here), "renders")
    os.makedirs(out_dir, exist_ok=True)
    for fname in sorted(os.listdir(examples_dir)):
        if not fname.endswith(".html"):
            continue
        html_path = os.path.join(examples_dir, fname)
        out_path = os.path.join(out_dir, fname.replace(".html", ".png"))
        doc, html_el = _load_page(html_path)
        root = build_root(html_el, 900)
        canvas = paint_tree(root, 900, viewport_height=max(root.height, 100))
        with open(out_path, "wb") as f:
            f.write(canvas.to_png_bytes())
        print(f"{fname} -> {out_path} ({canvas.width}x{canvas.height})")


def main():
    parser = argparse.ArgumentParser(prog="cascade")
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="render an HTML file to a PNG")
    p_render.add_argument("html")
    p_render.add_argument("--css", default=None)
    p_render.add_argument("--width", type=int, default=900)
    p_render.add_argument("--out", default="out.png")
    p_render.set_defaults(func=cmd_render)

    p_layout = sub.add_parser("layout", help="print the computed box tree")
    p_layout.add_argument("html")
    p_layout.add_argument("--css", default=None)
    p_layout.add_argument("--width", type=int, default=900)
    p_layout.set_defaults(func=cmd_layout)

    p_boxes = sub.add_parser("boxes-json", help="dump element boxes as JSON")
    p_boxes.add_argument("html")
    p_boxes.add_argument("--css", default=None)
    p_boxes.add_argument("--width", type=int, default=900)
    p_boxes.set_defaults(func=cmd_boxes_json)

    p_demo = sub.add_parser("demo", help="render every example page")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
