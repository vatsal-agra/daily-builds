"""Folio command-line interface."""

import argparse
import sys

from .engine import render_file


def cmd_render(args):
    try:
        page = render_file(args.input, viewport_width=args.width)
    except OSError as e:
        print(f"folio: error: could not read {args.input!r}: {e}", file=sys.stderr)
        return 1
    out = args.out or (args.input.rsplit(".", 1)[0] + ".png")
    page.save_png(out)
    print(f"folio: wrote {out} ({page.viewport_width}x{page.height})")
    return 0


def cmd_info(args):
    try:
        page = render_file(args.input, viewport_width=args.width)
    except OSError as e:
        print(f"folio: error: could not read {args.input!r}: {e}", file=sys.stderr)
        return 1
    print(f"viewport: {page.viewport_width}x{page.height}")
    print(f"paint commands: {len(page.paint_commands)}")
    from .dom import iter_descendants
    n_elements = sum(1 for _ in iter_descendants(page.document))
    print(f"DOM elements: {n_elements}")
    print(f"CSS rules (author): {len(__import__('folio.css_parser', fromlist=['parse_css']).parse_css(page.author_css).rules)}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="folio", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="render an HTML file to a PNG")
    p_render.add_argument("input", help="path to an .html file")
    p_render.add_argument("-o", "--out", help="output PNG path")
    p_render.add_argument("-w", "--width", type=int, default=800, help="viewport width in px")
    p_render.set_defaults(func=cmd_render)

    p_info = sub.add_parser("info", help="print DOM/CSS/layout stats for an HTML file")
    p_info.add_argument("input", help="path to an .html file")
    p_info.add_argument("-w", "--width", type=int, default=800, help="viewport width in px")
    p_info.set_defaults(func=cmd_info)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
