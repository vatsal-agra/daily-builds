"""Casement command-line interface."""

import argparse
import json
import sys

from . import render as render_mod


def cmd_render(args):
    with open(args.input, "r", encoding="utf-8") as f:
        html_text = f.read()
    extra_css = ""
    if args.css:
        with open(args.css, "r", encoding="utf-8") as f:
            extra_css = f.read()
    result = render_mod.render(html_text, extra_css=extra_css, viewport_width=args.width)
    with open(args.output, "wb") as f:
        f.write(result.png_bytes)
    print(f"Rendered {args.input} -> {args.output} ({result.width}x{result.height})")
    if args.json:
        layout_json = render_mod.export_layout_json(result.root_box)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(layout_json, f, indent=2)
        print(f"Layout tree -> {args.json}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="casement", description="A from-scratch HTML/CSS layout engine.")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("render", help="Render an HTML file to a PNG image.")
    r.add_argument("input", help="Path to an .html file")
    r.add_argument("-o", "--output", default="output.png", help="Output PNG path")
    r.add_argument("--css", help="Optional extra .css file to apply")
    r.add_argument("--width", type=int, default=800, help="Viewport width in px")
    r.add_argument("--json", help="Also export the computed layout tree as JSON")
    r.set_defaults(func=cmd_render)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
