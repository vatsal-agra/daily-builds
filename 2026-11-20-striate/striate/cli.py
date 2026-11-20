"""Command line: encode / decode / demo."""
import argparse
import json
import sys

from . import encode as _encode, scan_image, raster, svg, png
from .symbologies import NAMES, EncodeError


def _cmd_encode(a):
    b = _encode(a.symbology, a.text, mod43=a.mod43, check=a.check)
    if a.out.endswith(".svg"):
        open(a.out, "w").write(svg.to_svg(b, module=a.module, height=a.height))
    elif a.out.endswith(".png"):
        raster.render(b, module=a.module, height=a.height).save(a.out)
    else:
        raise SystemExit("error: --out must end in .svg or .png")
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
        if dets and rc == 1:
            rc = 0
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="striate", description="1D barcode encoder and image scanner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encode", help="encode text to an SVG/PNG file")
    e.add_argument("symbology", help="one of: " + ", ".join(NAMES))
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
    a = ap.parse_args(argv)
    try:
        if a.cmd == "encode":
            return _cmd_encode(a) or 0
        return _cmd_decode(a)
    except EncodeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
