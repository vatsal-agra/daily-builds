"""Casement command-line interface."""

import argparse
import json
import sys

from . import render as render_mod


class CasementCLIError(Exception):
    """A clean, user-facing CLI error (no Python traceback)."""


def _read_text_file(path, label):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise CasementCLIError(f"{label} not found: {path}")
    except IsADirectoryError:
        raise CasementCLIError(f"{label} is a directory, not a file: {path}")
    except UnicodeDecodeError:
        raise CasementCLIError(f"{label} is not valid UTF-8 text: {path}")


def cmd_render(args):
    if args.width <= 0:
        raise CasementCLIError(f"--width must be a positive integer, got {args.width}")
    html_text = _read_text_file(args.input, "input HTML file")
    extra_css = ""
    if args.css:
        extra_css = _read_text_file(args.css, "--css file")
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
    try:
        return args.func(args)
    except CasementCLIError as e:
        print(f"casement: error: {e}", file=sys.stderr)
        return 1
    except RecursionError:
        # The layout/paint/box-tree walks are recursive by DOM depth (this
        # is disclosed, not silently caught-and-ignored -- see PLAN.md);
        # a page nested many hundreds of elements deep hits Python's
        # recursion limit rather than a Casement-specific one.
        print(
            "casement: error: this page is nested too deeply for Casement's "
            "recursive layout engine to handle (Python's recursion limit). "
            "This is a known scope limit, not a crash bug -- see PLAN.md.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
