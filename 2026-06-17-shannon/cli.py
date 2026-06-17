#!/usr/bin/env python3
"""Shannon — command-line front end for the compression toolkit.

Subcommands:
    compress    compress a file into a .shz container (pick a codec or --best)
    decompress  restore the original file from a .shz container
    info        show the codec / size / ratio recorded in a .shz file
    analyze     entropy report + side-by-side codec comparison table
    viz         generate a self-contained interactive HTML report
    demo        run a self-checking end-to-end demonstration

Exit codes: 0 = ok, 1 = usage/error, 2 = corruption/verification failure.
"""
from __future__ import annotations

import argparse
import os
import sys

from shannon import codecs, container


def _read(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    with open(path, "rb") as f:
        return f.read()


def _write(path: str, data: bytes) -> None:
    if path == "-":
        sys.stdout.buffer.write(data)
    else:
        with open(path, "wb") as f:
            f.write(data)


def _best_method(data: bytes):
    """Return (name, blob) for the codec producing the smallest container."""
    best_name = None
    best_blob = None
    for name in codecs.ALL_NAMES:
        blob = container.pack(name, data)
        if best_blob is None or len(blob) < len(best_blob):
            best_name, best_blob = name, blob
    return best_name, best_blob


def cmd_compress(args) -> int:
    data = _read(args.input)
    if args.best:
        method, blob = _best_method(data)
    else:
        if args.method not in codecs.CODECS:
            print(f"error: unknown codec {args.method!r}; choose from "
                  f"{', '.join(codecs.ALL_NAMES)}", file=sys.stderr)
            return 1
        method = args.method
        blob = container.pack(method, data)

    # Always verify the round-trip before writing — never ship a bad archive.
    if container.unpack(blob) != data:
        print("error: internal round-trip verification failed", file=sys.stderr)
        return 2

    out = args.output or (args.input + ".shz")
    _write(out, blob)
    orig = len(data)
    comp = len(blob)
    ratio = (comp / orig) if orig else 0.0
    saved = (1 - ratio) * 100 if orig else 0.0
    print(f"{args.input} -> {out}")
    print(f"  codec   : {method}")
    print(f"  original: {orig} bytes")
    print(f"  packed  : {comp} bytes  ({ratio:.3f}x, {saved:.1f}% smaller)")
    return 0


def cmd_decompress(args) -> int:
    blob = _read(args.input)
    try:
        data = container.unpack(blob)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = args.output
    if out is None:
        out = args.input[:-4] if args.input.endswith(".shz") else args.input + ".out"
    _write(out, data)
    print(f"{args.input} -> {out}  ({len(data)} bytes, codec={container.method_name(blob)})")
    return 0


def cmd_info(args) -> int:
    blob = _read(args.input)
    try:
        data = container.unpack(blob)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    orig = len(data)
    comp = len(blob)
    print(f"file    : {args.input}")
    print(f"codec   : {container.method_name(blob)}")
    print(f"original: {orig} bytes")
    print(f"packed  : {comp} bytes")
    if orig:
        print(f"ratio   : {comp / orig:.3f}x ({(1 - comp / orig) * 100:.1f}% smaller)")
    print("integrity: OK (CRC verified)")
    return 0


def cmd_analyze(args) -> int:
    from shannon import analyze
    data = _read(args.input)
    print(analyze.report(data, label=args.input))
    return 0


def cmd_viz(args) -> int:
    from shannon import viz
    data = _read(args.input)
    html = viz.render(data, label=os.path.basename(args.input))
    out = args.output or (args.input + ".html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out} ({len(html)} bytes) — open it in a browser")
    return 0


def cmd_demo(args) -> int:
    from shannon import demo
    return demo.run()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shannon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compress", help="compress a file into .shz")
    c.add_argument("input")
    c.add_argument("-o", "--output")
    c.add_argument("-m", "--method", default="bwt",
                   help="codec: " + ", ".join(codecs.ALL_NAMES) + " (default: bwt)")
    c.add_argument("--best", action="store_true",
                   help="try every codec and keep the smallest")
    c.set_defaults(func=cmd_compress)

    d = sub.add_parser("decompress", help="restore a .shz file")
    d.add_argument("input")
    d.add_argument("-o", "--output")
    d.set_defaults(func=cmd_decompress)

    i = sub.add_parser("info", help="inspect a .shz file")
    i.add_argument("input")
    i.set_defaults(func=cmd_info)

    a = sub.add_parser("analyze", help="entropy report + codec comparison")
    a.add_argument("input")
    a.set_defaults(func=cmd_analyze)

    v = sub.add_parser("viz", help="generate an interactive HTML report")
    v.add_argument("input")
    v.add_argument("-o", "--output")
    v.set_defaults(func=cmd_viz)

    dm = sub.add_parser("demo", help="run a self-checking demonstration")
    dm.set_defaults(func=cmd_demo)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
