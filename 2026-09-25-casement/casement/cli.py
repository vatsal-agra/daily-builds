"""Casement command-line interface."""

import argparse
import json
import sys

from . import inspector as inspector_mod
from . import oracle as oracle_mod
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


def cmd_inspect(args):
    if args.width <= 0:
        raise CasementCLIError(f"--width must be a positive integer, got {args.width}")
    html_text = _read_text_file(args.input, "input HTML file")
    extra_css = ""
    if args.css:
        extra_css = _read_text_file(args.css, "--css file")
    html_out = inspector_mod.generate_inspector_html(html_text, extra_css=extra_css, viewport_width=args.width)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Inspector -> {args.output} (open it in a browser)")
    return 0


def cmd_compare(args):
    if args.width <= 0:
        raise CasementCLIError(f"--width must be a positive integer, got {args.width}")
    html_text = _read_text_file(args.input, "input HTML file")
    extra_css = ""
    if args.css:
        extra_css = _read_text_file(args.css, "--css file")
    try:
        diffs = oracle_mod.compare(html_text, extra_css=extra_css, viewport_width=args.width)
    except (RuntimeError, FileNotFoundError, OSError) as e:
        raise CasementCLIError(f"Chromium oracle unavailable: {e}")

    if not diffs:
        print("No tagged elements to compare.")
        return 0

    worst = max(diffs, key=lambda d: d.max_abs_diff)
    print(f"{'cid':>4} {'tag':<10} {'dx':>8} {'dy':>8} {'dw':>8} {'dh':>8}")
    for d in diffs:
        print(f"{d.cid:>4} {d.tag:<10} {d.dx:8.1f} {d.dy:8.1f} {d.dw:8.1f} {d.dh:8.1f}")
    print(f"\n{len(diffs)} elements compared; worst max-abs-diff = {worst.max_abs_diff:.2f}px (cid {worst.cid}, <{worst.tag}>)")
    if args.tolerance is not None:
        over = [d for d in diffs if d.max_abs_diff > args.tolerance]
        if over:
            print(f"FAIL: {len(over)} element(s) exceed tolerance {args.tolerance}px")
            return 1
        print(f"PASS: all elements within tolerance {args.tolerance}px")
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

    i = sub.add_parser("inspect", help="Render an HTML file to an interactive box-model inspector (HTML).")
    i.add_argument("input", help="Path to an .html file")
    i.add_argument("-o", "--output", default="inspector.html", help="Output HTML path")
    i.add_argument("--css", help="Optional extra .css file to apply")
    i.add_argument("--width", type=int, default=800, help="Viewport width in px")
    i.set_defaults(func=cmd_inspect)

    c = sub.add_parser("compare", help="Diff Casement's layout against real headless Chromium (a differential oracle).")
    c.add_argument("input", help="Path to an .html file")
    c.add_argument("--css", help="Optional extra .css file to apply")
    c.add_argument("--width", type=int, default=800, help="Viewport width in px")
    c.add_argument("--tolerance", type=float, default=None, help="Max allowed per-element px diff; exits 1 if exceeded")
    c.set_defaults(func=cmd_compare)

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
