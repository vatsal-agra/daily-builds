"""Folio command-line interface."""

import argparse
import sys

from .css_parser import parse_css
from .dom import iter_descendants
from .engine import render_file
from .inspector import render_inspector_html


def _load_page(args):
    """Shared input/width validation for every subcommand. Returns (page,
    exit_code_or_None) -- exit_code_or_None is only set on failure."""
    if args.width <= 0:
        print(f"folio: error: --width must be positive, got {args.width}", file=sys.stderr)
        return None, 1
    try:
        return render_file(args.input, viewport_width=args.width), None
    except OSError as e:
        print(f"folio: error: could not read {args.input!r}: {e}", file=sys.stderr)
        return None, 1


def cmd_render(args):
    page, err = _load_page(args)
    if err is not None:
        return err
    out = args.out or (args.input.rsplit(".", 1)[0] + ".png")
    page.save_png(out)
    # A page with zero laid-out content still yields a real, valid 1px-tall
    # PNG (Canvas floors height at 1) -- report that actual size, not the
    # pre-floor layout height, so this message never disagrees with the
    # file that just got written.
    print(f"folio: wrote {out} ({page.viewport_width}x{max(1, page.height)})")
    return 0


def cmd_info(args):
    page, err = _load_page(args)
    if err is not None:
        return err
    print(f"viewport: {page.viewport_width}x{page.height}")
    print(f"paint commands: {len(page.paint_commands)}")
    n_elements = sum(1 for _ in iter_descendants(page.document))
    print(f"DOM elements: {n_elements}")
    n_rules = len(parse_css(page.author_css).rules)
    print(f"CSS rules (author): {n_rules}")
    return 0


def cmd_inspect(args):
    page, err = _load_page(args)
    if err is not None:
        return err
    out = args.out or (args.input.rsplit(".", 1)[0] + ".inspector.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_inspector_html(page))
    print(f"folio: wrote {out}")
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

    p_inspect = sub.add_parser("inspect", help="render an interactive DOM/box-model inspector page")
    p_inspect.add_argument("input", help="path to an .html file")
    p_inspect.add_argument("-o", "--out", help="output HTML path")
    p_inspect.add_argument("-w", "--width", type=int, default=800, help="viewport width in px")
    p_inspect.set_defaults(func=cmd_inspect)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
