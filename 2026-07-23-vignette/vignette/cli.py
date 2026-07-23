"""Command-line interface: `vignette encode|decode|analyze|compare`."""

import argparse
import sys
import time

from . import encoder, decoder, metrics, png, visualize
from .image import Image, TEST_IMAGES


def cmd_encode(args):
    image = _load_input(args.input)
    data, stats = encoder.encode(
        image, quality=args.quality, optimal_huffman=args.optimal_huffman
    )
    with open(args.output, "wb") as f:
        f.write(data)
    cstats = metrics.compression_stats(image, data)
    print(
        f"encoded {image.width}x{image.height} at quality={args.quality} -> "
        f"{args.output} ({cstats['compressed_bytes']} bytes, "
        f"{cstats['ratio']:.2f}x smaller than raw RGB, "
        f"{cstats['bits_per_pixel']:.3f} bpp)"
    )
    if args.optimal_huffman:
        print(f"  optimal huffman tables used: {stats['used_optimal_huffman']}")


def cmd_decode(args):
    with open(args.input, "rb") as f:
        data = f.read()
    t0 = time.time()
    image = decoder.decode(data)
    dt = time.time() - t0
    if args.output.lower().endswith(".ppm"):
        image.save_ppm(args.output)
    else:
        png.save_png(image, args.output)
    print(f"decoded {image.width}x{image.height} in {dt:.3f}s -> {args.output}")


def cmd_analyze(args):
    image = _load_input(args.input)
    print(f"{args.input}: {image.width}x{image.height}")
    print(f"{'quality':>8} {'bytes':>10} {'ratio':>8} {'bpp':>8} "
          f"{'psnr(dB)':>10} {'ssim':>8}")
    for q in args.qualities:
        data, _ = encoder.encode(image, quality=q)
        recon = decoder.decode(data)
        cstats = metrics.compression_stats(image, data)
        p = metrics.psnr(image, recon)
        s = metrics.ssim(image, recon)
        p_str = "inf" if p == float("inf") else f"{p:.2f}"
        print(
            f"{q:>8} {cstats['compressed_bytes']:>10} {cstats['ratio']:>7.2f}x "
            f"{cstats['bits_per_pixel']:>8.3f} {p_str:>10} {s:>8.4f}"
        )


def cmd_report(args):
    path = visualize.build_report(args.output, size=args.size)
    print(f"wrote interactive HTML report -> {path}")


def cmd_compare(args):
    a = _load_input(args.a)
    b = _load_input(args.b)
    print(f"PSNR: {metrics.psnr(a, b):.3f} dB")
    print(f"SSIM: {metrics.ssim(a, b):.4f}")


def _load_input(spec):
    if spec in TEST_IMAGES:
        return TEST_IMAGES[spec](256, 256)
    return Image.load_ppm(spec)


def build_parser():
    p = argparse.ArgumentParser(prog="vignette", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("encode", help="encode an image to baseline JPEG")
    e.add_argument("input", help="PPM path, or a built-in test image name")
    e.add_argument("output", help="output .jpg path")
    e.add_argument("-q", "--quality", type=int, default=75)
    e.add_argument("--optimal-huffman", action="store_true")
    e.set_defaults(func=cmd_encode)

    d = sub.add_parser("decode", help="decode a JPEG to PNG or PPM")
    d.add_argument("input", help="input .jpg path")
    d.add_argument("output", help="output .png or .ppm path")
    d.set_defaults(func=cmd_decode)

    a = sub.add_parser("analyze", help="rate/distortion sweep over qualities")
    a.add_argument("input", help="PPM path, or a built-in test image name")
    a.add_argument(
        "--qualities", type=int, nargs="+",
        default=[95, 85, 75, 50, 25, 10],
    )
    a.set_defaults(func=cmd_analyze)

    r = sub.add_parser("report", help="build the interactive HTML report")
    r.add_argument("output", nargs="?", default="out/report.html")
    r.add_argument("--size", type=int, default=192)
    r.set_defaults(func=cmd_report)

    c = sub.add_parser("compare", help="PSNR/SSIM between two PPM images")
    c.add_argument("a")
    c.add_argument("b")
    c.set_defaults(func=cmd_compare)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, decoder.JpegSyntaxError, EOFError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
