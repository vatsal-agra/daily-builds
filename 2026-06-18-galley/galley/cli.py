"""Command-line interface for Galley."""

from __future__ import annotations

import argparse
import sys
from typing import List

from .metrics import Font, available_families
from .model import build_paragraph
from .hyphen import Hyphenator
from .linebreak import break_paragraph, greedy_break, evaluate_breaks
from .render import (
    render_svg, render_ascii, ascii_paragraph,
    render_card, render_html_document,
)
from .verify import roundtrip_words, count_rivers

SAMPLE = (
    "In olden times when wishing still helped one, there lived a king whose "
    "daughters were all beautiful, but the youngest was so beautiful that the "
    "sun itself, which has seen so much, was astonished whenever it shone in "
    "her face. Close by the king's castle lay a great dark forest, and under "
    "an old lime tree in the forest was a well, and when the day was very warm, "
    "the king's child went out into the forest and sat down by the side of the "
    "cool fountain, and when she was bored she took a golden ball, and threw it "
    "up on high and caught it, and this ball was her favourite plaything."
)


def _read_text(args) -> str:
    if getattr(args, "text", None):
        return args.text
    if getattr(args, "file", None):
        with open(args.file, encoding="utf-8") as fh:
            return fh.read().strip()
    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            return data
    return SAMPLE


def _stats(breaking) -> List:
    lines = breaking.lines
    rs = [abs(l.ratio) for l in lines[:-1]] if len(lines) > 1 else [0.0]
    avg_r = sum(rs) / len(rs) if rs else 0.0
    overfull = sum(1 for l in lines if l.ratio < -1.0 - 1e-9)
    hyphens = sum(1 for l in lines if l.flagged)
    return [
        ("lines", str(len(lines))),
        ("demerits", f"{breaking.total_demerits:,.0f}" if breaking.feasible else "∞"),
        ("avg |r|", f"{avg_r:.2f}"),
        ("hyphens", str(hyphens)),
        ("overfull", str(overfull)),
    ]


# --------------------------------------------------------------------------- #

def cmd_hyphenate(args) -> int:
    h = Hyphenator()
    words = args.words or _read_text(args).split()
    for w in words:
        core = "".join(c for c in w if c.isalpha())
        frags = h.hyphenate(core) if core else [w]
        print(f"{w:<22} {'-'.join(frags)}")
    return 0


def cmd_break(args) -> int:
    h = Hyphenator() if not args.no_hyphenate else None
    text = _read_text(args)
    hyph = h.hyphenate if h else None
    ap = ascii_paragraph(text, hyphenate=hyph)
    width = int(round(args.width))
    if args.method == "greedy":
        br = greedy_break(ap.items, float(width))
    else:
        br = break_paragraph(ap.items, float(width))
    lines = render_ascii(ap.items, br, justify=not args.ragged)
    rule = "+" + "-" * width + "+"
    print(rule)
    for l in lines:
        print("|" + l.ljust(width)[:width] + "|")
    print(rule)
    s = _stats(br)
    print("  " + "   ".join(f"{k}: {v}" for k, v in s))
    ok, msg = roundtrip_words(ap.items, br, ap.words)
    print(f"  round-trip: {'OK' if ok else 'FAIL — ' + msg}")
    return 0 if ok else 1


def cmd_render(args) -> int:
    h = Hyphenator() if not args.no_hyphenate else None
    text = _read_text(args)
    font = Font(args.font, args.size)
    para = build_paragraph(text, font, hyphenate=(h.hyphenate if h else None))
    measure = float(args.width)
    if args.method == "greedy":
        br = greedy_break(para.items, measure)
    else:
        br = break_paragraph(para.items, measure)
    svg = render_svg(para.items, br, font, measure, heat=args.heat,
                     title=args.title)
    _write(args.output, svg)
    print(f"wrote {args.output}  ({len(br.lines)} lines, "
          f"{'feasible' if br.feasible else 'has overfull lines'})")
    return 0


def cmd_compare(args) -> int:
    h = Hyphenator()
    text = _read_text(args)
    font = Font(args.font, args.size)
    measure = float(args.width)
    para = build_paragraph(text, font, hyphenate=h.hyphenate)
    kp = break_paragraph(para.items, measure)
    gr = greedy_break(para.items, measure)
    gr_scored = evaluate_breaks(para.items, gr.breaks, measure)

    def row(name, br):
        s = dict(_stats(br))
        print(f"  {name:<14} lines={s['lines']:<3} demerits={s['demerits']:<14} "
              f"avg|r|={s['avg |r|']:<6} hyphens={s['hyphens']} overfull={s['overfull']}")

    print(f"Comparing on measure={measure:g}pt, font={font.psname} {font.size:g}pt\n")
    row("Knuth-Plass", kp)
    row("greedy", gr_scored)
    if kp.feasible and gr_scored.feasible and gr_scored.total_demerits > 0:
        ratio = gr_scored.total_demerits / max(kp.total_demerits, 1e-9)
        print(f"\n  Greedy costs {ratio:.2f}x the demerits of the optimal breaking.")
    elif not gr_scored.feasible:
        print("\n  Greedy produced overfull line(s); Knuth-Plass did not.")

    if args.output:
        cards = []
        cards.append(render_card(
            "Knuth–Plass (optimal)",
            f"{len(kp.lines)} lines · demerits {kp.total_demerits:,.0f}",
            render_svg(para.items, kp, font, measure, heat=True), _stats(kp)))
        cards.append(render_card(
            "Greedy (first-fit)",
            f"{len(gr.lines)} lines · "
            + ("demerits %s" % (f"{gr_scored.total_demerits:,.0f}" if gr_scored.feasible else "∞")),
            render_svg(para.items, gr, font, measure, heat=True), _stats(gr_scored)))
        doc = render_html_document(
            'Galley · <span class="accent">optimal</span> vs greedy line breaking',
            f"Same paragraph set in {font.psname} at {font.size:g}pt on a "
            f"{measure:g}pt measure. Greener lines are more evenly spaced.",
            cards,
            footer="Generated by Galley — Knuth–Plass total-fit typesetting.")
        _write(args.output, doc)
        print(f"\n  wrote {args.output}")
    return 0


def cmd_playground(args) -> int:
    from .playground import build_playground
    text = _read_text(args)
    html = build_playground(text, font_family=args.font, size=args.size)
    _write(args.output, html)
    print(f"wrote interactive playground to {args.output}")
    return 0


def cmd_rivers(args) -> int:
    h = Hyphenator()
    text = _read_text(args)
    font = Font(args.font, args.size)
    measure = float(args.width)
    para = build_paragraph(text, font, hyphenate=h.hyphenate)
    br = break_paragraph(para.items, measure)
    rivers = count_rivers(para.items, br, font)
    print(f"measure={measure:g}pt  lines={len(br.lines)}  "
          f"rivers found: {len(rivers)}")
    for rv in rivers[:12]:
        print(f"  river: rows {rv['start_line']}–{rv['end_line']} "
              f"(length {rv['length']}), ~x={rv['x']:.0f}pt")
    return 0


def cmd_demo(args) -> int:
    from .demo import run_demo
    return run_demo(args.outdir)


# --------------------------------------------------------------------------- #

def _write(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _add_text_args(p, width_default, with_method=True):
    p.add_argument("--text", help="literal text to typeset")
    p.add_argument("--file", help="read text from a file")
    p.add_argument("--width", type=float, default=width_default,
                   help="measure (column width)")
    p.add_argument("--font", default="times", choices=available_families(),
                   help="font family")
    p.add_argument("--size", type=float, default=11.0, help="point size")
    p.add_argument("--no-hyphenate", action="store_true",
                   help="disable hyphenation")
    if with_method:
        p.add_argument("--method", default="kp", choices=["kp", "greedy"],
                       help="breaking algorithm")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="galley",
        description="Galley — optimal typesetting (Knuth–Plass line breaking).")
    sub = p.add_subparsers(dest="command", required=True)

    hp = sub.add_parser("hyphenate", help="show Liang hyphenation of words")
    hp.add_argument("words", nargs="*", help="words to hyphenate")
    hp.add_argument("--text", help=argparse.SUPPRESS)
    hp.add_argument("--file", help=argparse.SUPPRESS)
    hp.set_defaults(func=cmd_hyphenate)

    bp = sub.add_parser("break", help="break a paragraph into an ASCII column")
    _add_text_args(bp, 60)
    bp.add_argument("--ragged", action="store_true", help="ragged-right (no justify)")
    bp.set_defaults(func=cmd_break)

    rp = sub.add_parser("render", help="render a justified paragraph to SVG")
    _add_text_args(rp, 320)
    rp.add_argument("-o", "--output", default="galley.svg")
    rp.add_argument("--heat", action="store_true", help="color lines by badness")
    rp.add_argument("--title", default=None)
    rp.set_defaults(func=cmd_render)

    cp = sub.add_parser("compare", help="compare Knuth–Plass vs greedy")
    _add_text_args(cp, 320, with_method=False)
    cp.add_argument("-o", "--output", help="also write an HTML comparison")
    cp.set_defaults(func=cmd_compare)

    pp = sub.add_parser("playground", help="generate an interactive HTML playground")
    pp.add_argument("--text", help="literal text")
    pp.add_argument("--file", help="read text from a file")
    pp.add_argument("--font", default="times", choices=available_families())
    pp.add_argument("--size", type=float, default=12.0)
    pp.add_argument("-o", "--output", default="galley-playground.html")
    pp.set_defaults(func=cmd_playground)

    vp = sub.add_parser("rivers", help="detect whitespace rivers in a set paragraph")
    _add_text_args(vp, 300, with_method=False)
    vp.set_defaults(func=cmd_rivers)

    dp = sub.add_parser("demo", help="generate a full tour of artifacts")
    dp.add_argument("--outdir", default="demo_out")
    dp.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
