#!/usr/bin/env python3
"""Folio CLI: drive every stage of the pipeline from the command line."""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from folio.html_parser import parse_html
from folio.dom import pretty, find_element
from folio.cascade import compute_style_tree
from folio.layout import layout_subtree
from folio.paint import paint_svg, page_height
from folio.values import Length


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_css(args):
    texts = []
    for path in args.css or []:
        texts.append(_read(path))
    return texts


def cmd_parse(args):
    doc = parse_html(_read(args.html))
    print(pretty(doc))


def cmd_cascade(args):
    doc = parse_html(_read(args.html))
    styles = compute_style_tree(doc, _load_css(args))
    for el, st in styles.items():
        indent = "  " * _depth(el)
        print("%s%r" % (indent, el))
        for prop in sorted(("display", "width", "color", "font-size", "margin-top")):
            print("%s    %s: %r" % (indent, prop, st.get(prop)))


def _depth(el):
    d = 0
    n = el
    while n.parent is not None:
        d += 1
        n = n.parent
    return d


def cmd_layout(args):
    doc = parse_html(_read(args.html))
    styles = compute_style_tree(doc, _load_css(args))
    body = find_element(doc, "body") or doc
    root = layout_subtree(body, styles, args.width)

    def dump(box, depth=0):
        tag = "anon" if box.is_anonymous else (box.element.tag if box.element else "#root")
        x, y, w, h = box.rect()
        print("%s<%s> x=%.1f y=%.1f w=%.1f h=%.1f mode=%s" % ("  " * depth, tag, x, y, w, h, box.mode))
        for c in box.block_children:
            dump(c, depth + 1)

    dump(root)


def cmd_render(args):
    doc = parse_html(_read(args.html))
    styles = compute_style_tree(doc, _load_css(args))
    body = find_element(doc, "body") or doc
    root = layout_subtree(body, styles, args.width)
    height = page_height(root)
    svg = paint_svg(root, args.width, max(height, 10))
    out_path = args.output or (os.path.splitext(args.html)[0] + ".svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote %s (%.0fx%.0f)" % (out_path, args.width, height))


def cmd_demo(args):
    from folio import demo as demo_mod

    demo_mod.run(args.outdir)


def main(argv=None):
    p = argparse.ArgumentParser(prog="folio")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("html")
        sp.add_argument("--css", action="append", help="extra author stylesheet file(s)")

    sp = sub.add_parser("parse", help="parse HTML -> DOM tree dump")
    sp.add_argument("html")
    sp.set_defaults(func=cmd_parse)

    sp = sub.add_parser("cascade", help="show computed styles")
    add_common(sp)
    sp.set_defaults(func=cmd_cascade)

    sp = sub.add_parser("layout", help="show the box-model layout tree")
    add_common(sp)
    sp.add_argument("--width", type=float, default=800)
    sp.set_defaults(func=cmd_layout)

    sp = sub.add_parser("render", help="render to SVG")
    add_common(sp)
    sp.add_argument("--width", type=float, default=800)
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("demo", help="run the bundled demo suite")
    sp.add_argument("--outdir", default="demo_out")
    sp.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
