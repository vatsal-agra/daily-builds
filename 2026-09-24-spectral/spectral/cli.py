"""The `spectral` command-line interface."""
import argparse
import time

from . import bmp, decoder, dct, encoder, metrics, png_reader, testimages
from .markers import JpegParseError
from .decoder import JpegDecodeError


def _load_image(path):
    if path.lower().endswith(".bmp"):
        loader = bmp.read_bmp
    elif path.lower().endswith(".png"):
        loader = png_reader.read_png
    else:
        raise SystemExit(f"error: unsupported input format for {path!r} (use .bmp or .png)")
    try:
        return loader(path)
    except FileNotFoundError:
        raise SystemExit(f"error: no such file: {path!r}")
    except (ValueError, OSError) as e:
        raise SystemExit(f"error: could not read {path!r}: {e}")


def _read_file(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        raise SystemExit(f"error: no such file: {path!r}")
    except OSError as e:
        raise SystemExit(f"error: could not read {path!r}: {e}")


def _write_file(path, data):
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as e:
        raise SystemExit(f"error: could not write {path!r}: {e}")


def cmd_encode(args):
    if args.progressive and args.optimize:
        raise SystemExit("error: --optimize is not supported together with --progressive (progressive scans always use the standard Huffman tables)")
    try:
        if args.test_image:
            if args.test_image not in testimages.ALL_GENERATORS:
                raise SystemExit(f"error: unknown test image {args.test_image!r} (choices: {sorted(testimages.ALL_GENERATORS)})")
            image = testimages.ALL_GENERATORS[args.test_image](args.width, args.height)
        elif args.input:
            image = _load_image(args.input)
        else:
            raise SystemExit("error: specify --input or --test-image")

        if args.progressive:
            from . import progressive
            data = progressive.encode(image, quality=args.quality, subsampling=args.subsampling)
        else:
            data = encoder.encode(
                image, quality=args.quality, subsampling=args.subsampling,
                optimize_huffman=args.optimize,
            )
    except ImportError:
        raise SystemExit("error: --progressive is not available yet")
    except ValueError as e:
        raise SystemExit(f"error: {e}")

    _write_file(args.output, data)
    print(f"wrote {args.output}: {len(data)} bytes ({image.width}x{image.height}, quality={args.quality}, subsampling={args.subsampling})")


def cmd_decode(args):
    data = _read_file(args.input)
    try:
        try:
            from . import progressive
        except ImportError:
            progressive = None
        if progressive is not None and progressive.is_progressive(data):
            image = progressive.decode(data)
        else:
            image = decoder.decode(data)
    except (JpegParseError, JpegDecodeError) as e:
        raise SystemExit(f"error: could not decode {args.input!r}: {e}")

    if not args.output.lower().endswith(".bmp"):
        raise SystemExit("error: decode output must be a .bmp path")
    try:
        bmp.write_bmp(args.output, image)
    except OSError as e:
        raise SystemExit(f"error: could not write {args.output!r}: {e}")
    print(f"wrote {args.output}: {image.width}x{image.height}")


def cmd_compare(args):
    if args.test_image not in testimages.ALL_GENERATORS:
        raise SystemExit(f"error: unknown test image {args.test_image!r}")
    try:
        image = testimages.ALL_GENERATORS[args.test_image](args.width, args.height)
        print(f"{'quality':>7} {'subsample':>9} {'bytes':>7} {'ratio':>7} {'psnr(dB)':>9}")
        raw_size = image.width * image.height * 3
        for q in args.qualities:
            for ss in ("444", "422", "420"):
                data = encoder.encode(image, quality=q, subsampling=ss)
                out = decoder.decode(data)
                p = metrics.psnr(image, out)
                ratio = raw_size / len(data)
                print(f"{q:7d} {ss:>9} {len(data):7d} {ratio:6.1f}x {p:9.2f}")
    except ValueError as e:
        raise SystemExit(f"error: {e}")


def cmd_dct_demo(args):
    import random
    rng = random.Random(42)
    block = [rng.uniform(-128, 127) for _ in range(64)]
    fast = dct.dct_2d(block)
    naive = dct.dct_2d_naive(block)
    max_diff = max(abs(a - b) for a, b in zip(fast, naive))
    print(f"forward DCT: separable-matrix vs brute-force O(N^4) max abs diff = {max_diff:.2e}")
    recon = dct.idct_2d(fast)
    max_round_trip = max(abs(a - b) for a, b in zip(block, recon))
    print(f"round trip (forward then inverse) max abs diff = {max_round_trip:.2e}")


def cmd_viz(args):
    try:
        from . import viz
    except ImportError:
        raise SystemExit("error: viz is not available yet")
    viz.build(args.output, seed=args.seed)
    print(f"wrote {args.output}")


def cmd_demo(args):
    print("=== Spectral demo ===")
    t0 = time.time()
    image = testimages.synthetic_photo(96, 96, seed=99)
    for q in (10, 50, 90):
        data = encoder.encode(image, quality=q, subsampling="420")
        out = decoder.decode(data)
        p = metrics.psnr(image, out)
        print(f"quality={q:3d}: {len(data):5d} bytes, PSNR={p:.2f} dB")
    print(f"done in {time.time() - t0:.2f}s")


def build_parser():
    p = argparse.ArgumentParser(prog="spectral", description="A from-scratch JPEG codec.")
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("encode", help="encode a BMP/PNG image to JPEG")
    pe.add_argument("--input")
    pe.add_argument("--test-image", choices=sorted(testimages.ALL_GENERATORS))
    pe.add_argument("--width", type=int, default=64)
    pe.add_argument("--height", type=int, default=64)
    pe.add_argument("--output", required=True)
    pe.add_argument("--quality", type=int, default=75)
    pe.add_argument("--subsampling", choices=("444", "422", "420"), default="420")
    pe.add_argument("--optimize", action="store_true", help="build optimized per-image Huffman tables")
    pe.add_argument("--progressive", action="store_true", help="write a progressive JPEG")
    pe.set_defaults(func=cmd_encode)

    pd = sub.add_parser("decode", help="decode a JPEG to BMP")
    pd.add_argument("input")
    pd.add_argument("--output", required=True)
    pd.set_defaults(func=cmd_decode)

    pc = sub.add_parser("compare", help="rate-distortion sweep over quality/subsampling")
    pc.add_argument("--test-image", default="photo", choices=sorted(testimages.ALL_GENERATORS))
    pc.add_argument("--width", type=int, default=96)
    pc.add_argument("--height", type=int, default=96)
    pc.add_argument("--qualities", type=int, nargs="+", default=[10, 30, 50, 70, 85, 95])
    pc.set_defaults(func=cmd_compare)

    pdct = sub.add_parser("dct-demo", help="prove the fast DCT matches a brute-force reference")
    pdct.set_defaults(func=cmd_dct_demo)

    pv = sub.add_parser("viz", help="generate the interactive HTML visualizer")
    pv.add_argument("--output", default="spectral_viz.html")
    pv.add_argument("--seed", type=int, default=1)
    pv.set_defaults(func=cmd_viz)

    pdm = sub.add_parser("demo", help="run a short end-to-end demonstration")
    pdm.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
