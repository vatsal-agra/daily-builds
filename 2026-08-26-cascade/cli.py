#!/usr/bin/env python3
"""Cascade CLI.

    cascade render page.html [-o out.svg] [--width 800] [--css extra.css]
    cascade dump-boxes page.html [--width 800]
    cascade dump-styles page.html [--width 800]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cascade.engine import render_html  # noqa: E402
from cascade.dom import Element  # noqa: E402


def cmd_render(args):
    html = open(args.file, encoding="utf-8").read()
    extra_css = open(args.css, encoding="utf-8").read() if args.css else ""
    result = render_html(html, extra_css=extra_css, viewport_width=args.width)
    out = args.output or (os.path.splitext(args.file)[0] + ".svg")
    with open(out, "w", encoding="utf-8") as f:
        f.write(result.svg)
    print(f"wrote {out} ({len(result.svg)} bytes)")


def cmd_dump_boxes(args):
    html = open(args.file, encoding="utf-8").read()
    extra_css = open(args.css, encoding="utf-8").read() if args.css else ""
    result = render_html(html, extra_css=extra_css, viewport_width=args.width)

    def show(box, depth=0):
        tag = box.node.tag if isinstance(box.node, Element) else "[anon]"
        c = box.dims.content
        print(f"{'  ' * depth}<{tag}> content=({c.x:.1f},{c.y:.1f} {c.width:.1f}x{c.height:.1f})")
        for child in box.children:
            show(child, depth + 1)

    if result.box:
        show(result.box)
    else:
        print("(empty document)")


def cmd_dump_styles(args):
    html = open(args.file, encoding="utf-8").read()
    extra_css = open(args.css, encoding="utf-8").read() if args.css else ""
    result = render_html(html, extra_css=extra_css, viewport_width=args.width)
    for el, style in result.styles.items():
        print(repr(el))
        for prop in ("display", "width", "height", "color", "background-color", "font-size"):
            print(f"    {prop}: {style.get(prop)}")


def main():
    p = argparse.ArgumentParser(prog="cascade")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, fn in (("render", cmd_render), ("dump-boxes", cmd_dump_boxes), ("dump-styles", cmd_dump_styles)):
        sp = sub.add_parser(name)
        sp.add_argument("file")
        sp.add_argument("--width", type=int, default=800)
        sp.add_argument("--css", default=None, help="extra CSS file to apply after the page's own <style>")
        if name == "render":
            sp.add_argument("-o", "--output", default=None)
        sp.set_defaults(func=fn)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
