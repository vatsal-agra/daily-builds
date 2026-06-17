#!/usr/bin/env python3
"""Cinch command-line interface.

    cinch compress   <infile> [-o out] [-m method] [--max-chain N]
    cinch decompress <infile.cinch> [-o out]
    cinch inspect    <infile.cinch>
    cinch bench      [-m method...] [--corpus]   # ratio + speed table
    cinch roundtrip  <infile>                    # verify every method on a file
    cinch viz        [-o out.html] [--text STR]  # write the HTML visualizer
    cinch demo                                   # end-to-end demonstration
"""
from __future__ import annotations

import argparse
import sys
import time

import container as C
import corpus

METHOD_NAMES = ["store", "huffman", "lz77", "deflate", "range0", "range1"]


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


def cmd_compress(args) -> int:
    data = _read(args.infile)
    try:
        blob = C.compress(data, args.method)
    except C.CinchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = args.output or (args.infile + ".cinch")
    _write(out, blob)
    ratio = len(blob) / len(data) if data else float("nan")
    print(f"{args.infile}: {len(data)} -> {len(blob)} bytes "
          f"({args.method}, {(1 - ratio) * 100:.1f}% saved)" if data else
          f"{args.infile}: empty -> {len(blob)} bytes", file=sys.stderr)
    return 0


def cmd_decompress(args) -> int:
    blob = _read(args.infile)
    try:
        data = C.decompress(blob)
    except C.CinchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = args.output
    if out is None:
        out = args.infile[:-6] if args.infile.endswith(".cinch") else args.infile + ".out"
    _write(out, data)
    print(f"{args.infile}: -> {len(data)} bytes (verified)", file=sys.stderr)
    return 0


def cmd_inspect(args) -> int:
    blob = _read(args.infile)
    try:
        info = C.inspect(blob)
    except C.CinchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"file        : {args.infile}")
    print(f"format      : Cinch v{info['version']}")
    print(f"method      : {info['method']} (id {info['method_id']})")
    print(f"crc32       : {info['crc32']:#010x}")
    print(f"original    : {info['original_size']} bytes")
    print(f"compressed  : {info['compressed_size']} bytes "
          f"(header {info['header_size']}, payload {info['payload_size']})")
    if info["original_size"]:
        print(f"ratio       : {info['ratio']:.4f}  ({info['saving'] * 100:.1f}% saved)")
    return 0


def _fmt(n: float) -> str:
    return f"{n:8.3f}"


def cmd_bench(args) -> int:
    import bz2
    import lzma
    import zlib

    items = corpus.all_corpus()
    if args.file:
        items = {args.file: _read(args.file)}
    methods = args.methods or METHOD_NAMES

    refs = {
        "zlib-9": lambda d: zlib.compress(d, 9),
        "bz2-9": lambda d: bz2.compress(d, 9),
        "lzma": lambda d: lzma.compress(d),
    }

    colw = 12
    header = f"{'corpus':<18}{'size':>9}  " + "".join(f"{m:>{colw}}" for m in methods)
    header += "".join(f"{r:>{colw}}" for r in refs)
    print(header)
    print("-" * len(header))
    for name, data in items.items():
        row = f"{name:<18}{len(data):>9}  "
        for m in methods:
            blob = C.compress(data, m)
            assert C.decompress(blob) == data, f"roundtrip failed: {name}/{m}"
            ratio = len(blob) / len(data) if data else 0.0
            row += f"{ratio:>{colw}.3f}"
        for _rname, rfn in refs.items():
            comp = rfn(data)
            ratio = len(comp) / len(data) if data else 0.0
            row += f"{ratio:>{colw}.3f}"
        print(row)
    print("\n(values are compressed/original ratio — lower is better; "
          "every Cinch result was round-trip + CRC verified)")
    return 0


def cmd_roundtrip(args) -> int:
    data = _read(args.infile)
    print(f"{args.infile}: {len(data)} bytes")
    ok = True
    for m in METHOD_NAMES + ["auto"]:
        t0 = time.perf_counter()
        blob = C.compress(data, m)
        t1 = time.perf_counter()
        back = C.decompress(blob)
        t2 = time.perf_counter()
        good = back == data
        ok = ok and good
        ratio = len(blob) / len(data) if data else float("nan")
        flag = "ok " if good else "FAIL"
        print(f"  {m:<9} {flag} {len(blob):>8} bytes  ratio={ratio:6.3f}  "
              f"enc={(t1 - t0) * 1e3:7.1f}ms dec={(t2 - t1) * 1e3:7.1f}ms")
    print("ALL VERIFIED" if ok else "ROUNDTRIP FAILURE")
    return 0 if ok else 1


def cmd_viz(args) -> int:
    import viz
    html = viz.render(args.text)
    out = args.output or "cinch_viz.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out} ({len(html)} bytes) — open it in a browser", file=sys.stderr)
    return 0


def cmd_demo(args) -> int:
    print("=" * 64)
    print("CINCH — end-to-end demonstration")
    print("=" * 64)
    text = corpus.english(1500)
    print(f"\n1) Compress {len(text)} bytes of pseudo-English with every method:\n")
    cmd_bench(argparse.Namespace(methods=None, file=None))
    print("\n2) Container round-trip with CRC verification (deflate):")
    blob = C.compress(text, "deflate")
    info = C.inspect(blob)
    print(f"   {len(text)} -> {len(blob)} bytes, method={info['method']}, "
          f"crc={info['crc32']:#010x}")
    back = C.decompress(blob)
    print(f"   decompressed and verified: {back == text}")
    print("\n3) Corruption is detected (flip one payload byte):")
    bad = bytearray(blob)
    bad[-1] ^= 0xFF
    try:
        C.decompress(bytes(bad))
        print("   ERROR: corruption not detected!")
    except C.CinchError as e:
        print(f"   rejected as expected: {e}")
    print("\nDemo complete.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cinch", description="from-scratch compression toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compress")
    c.add_argument("infile")
    c.add_argument("-o", "--output")
    c.add_argument("-m", "--method", default="auto",
                   choices=METHOD_NAMES + ["auto"])
    c.add_argument("--max-chain", type=int, default=128)
    c.set_defaults(func=cmd_compress)

    d = sub.add_parser("decompress")
    d.add_argument("infile")
    d.add_argument("-o", "--output")
    d.set_defaults(func=cmd_decompress)

    i = sub.add_parser("inspect")
    i.add_argument("infile")
    i.set_defaults(func=cmd_inspect)

    b = sub.add_parser("bench")
    b.add_argument("-m", "--methods", nargs="+", choices=METHOD_NAMES)
    b.add_argument("-f", "--file")
    b.set_defaults(func=cmd_bench)

    r = sub.add_parser("roundtrip")
    r.add_argument("infile")
    r.set_defaults(func=cmd_roundtrip)

    v = sub.add_parser("viz")
    v.add_argument("-o", "--output")
    v.add_argument("--text", default="abracadabra abracadabra")
    v.set_defaults(func=cmd_viz)

    s = sub.add_parser("demo")
    s.set_defaults(func=cmd_demo)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
