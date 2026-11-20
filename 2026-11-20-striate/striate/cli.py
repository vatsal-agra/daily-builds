"""Command line: encode / decode / demo."""
import argparse
import json
import sys

from . import encode as _encode, scan_image, raster, svg, png, gs1
from .symbologies import NAMES, EncodeError


def _cmd_encode(a):
    text = a.text
    if a.symbology.lower() in ("gs1", "gs1-128", "gs1128"):
        try:
            text = gs1.build(a.text)
        except gs1.GS1Error as e:
            raise EncodeError(str(e))
        a.symbology = "code128"
    b = _encode(a.symbology, text, mod43=a.mod43, check=a.check)
    if a.out.endswith(".svg"):
        with open(a.out, "w") as f:
            f.write(svg.to_svg(b, module=a.module, height=a.height))
    elif a.out.endswith(".png"):
        raster.render(b, module=a.module, height=a.height).save(a.out)
    else:
        raise EncodeError("--out must end in .svg or .png")
    print(f"{b.symbology}  {b.text!r}  {len(b.modules)} modules -> {a.out}")


def _cmd_decode(a):
    rc = 1
    for path in a.images:
        try:
            img = raster.Image.load(path)
        except (OSError, png.PNGError) as e:
            print(f"{path}: error: {e}", file=sys.stderr)
            rc = 2
            continue
        dets = scan_image(img, rotate=not a.no_rotate)
        if a.json:
            print(json.dumps({"file": path, "barcodes": [d.as_dict() for d in dets]}))
        elif not dets:
            print(f"{path}: no barcode found")
        else:
            for d in dets:
                t = d.text.replace("\xf1", "<FNC1>")
                print(f"{path}: {d.symbology}  {t}  (votes={d.votes}, angle={d.angle:g}, bbox={d.bbox})")
                for ai, name, val, meaning in d.extra.get("gs1_fields", []):
                    print(f"    ({ai}) {name:<16} {val}" + (f"   = {meaning}" if meaning else ""))
                if d.extra.get("gs1_error"):
                    print(f"    GS1 parse problem: {d.extra['gs1_error']}")
        if dets and rc == 1:
            rc = 0
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="striate", description="1D barcode encoder and image scanner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encode", help="encode text to an SVG/PNG file")
    e.add_argument("symbology", help="one of: " + ", ".join(NAMES) + ", gs1 (text like '(01)09501101530003(10)LOT')")
    e.add_argument("text")
    e.add_argument("-o", "--out", required=True)
    e.add_argument("--module", type=int, default=3, help="module width in px/units")
    e.add_argument("--height", type=int, default=80)
    e.add_argument("--mod43", action="store_true", help="Code 39: append mod-43 check char")
    e.add_argument("--check", action="store_true", help="ITF: append mod-10 check digit")
    d = sub.add_parser("decode", help="find and decode barcodes in PNG/PGM images")
    d.add_argument("images", nargs="+")
    d.add_argument("--json", action="store_true")
    d.add_argument("--no-rotate", action="store_true", help="only scan horizontally")
    g = sub.add_parser("gallery", help="write a self-contained HTML gallery (live encodes + decodes)")
    g.add_argument("-o", "--out", default="gallery.html")
    g.add_argument("--bench", action="store_true", help="also run the robustness benchmark and embed charts (slow)")
    g.add_argument("-n", type=int, default=6, help="trials per benchmark cell")
    b = sub.add_parser("bench", help="decode success rate vs blur/noise/gain/module size")
    b.add_argument("sweeps", nargs="*", help="subset of: blur noise gain module (default all)")
    b.add_argument("-n", type=int, default=6, help="trials per cell")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "encode":
            return _cmd_encode(a) or 0
        if a.cmd == "bench":
            from . import bench
            if a.n < 1:
                raise EncodeError("-n must be >= 1")
            try:
                print(bench.format_table(bench.run(a.sweeps or None, n=a.n)))
            except ValueError as e:
                raise EncodeError(str(e))
            return 0
        if a.cmd == "gallery":
            from . import gallery, bench
            res = bench.run(n=a.n) if a.bench else None
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(gallery.build_html(res))
            print(f"wrote {a.out}")
            return 0
        return _cmd_decode(a)
    except EncodeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
