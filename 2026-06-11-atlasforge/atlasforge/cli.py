"""Command-line interface for Atlasforge."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time

from . import __version__
from .render import world_stats, write_html
from .worldgen import World, generate


def world_to_dict(world: World) -> dict:
    return {
        "version": __version__,
        "seed": world.seed,
        "width": world.width,
        "height": world.height,
        "sea_level": world.sea_level,
        "elevation": [round(v, 4) for v in world.elevation],
        "temperature": [round(v, 4) for v in world.temperature],
        "moisture": [round(v, 4) for v in world.moisture],
        "biome": world.biome,
        "rivers": world.hydrology.rivers,
        "lake": [int(v) for v in world.hydrology.lake],
        "settlements": [
            {
                "name": s.name, "x": s.x, "y": s.y, "kind": s.kind,
                "population": s.population, "founded": s.founded, "note": s.note,
            }
            for s in world.settlements
        ],
        "stats": world_stats(world),
    }


def positive_int(limit: int):
    def parse(text: str) -> int:
        try:
            v = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text!r} is not an integer")
        if v < 16 or v > limit:
            raise argparse.ArgumentTypeError(f"must be between 16 and {limit}")
        return v

    return parse


def land_fraction(text: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number")
    if not 0.05 <= v <= 0.95:
        raise argparse.ArgumentTypeError("land fraction must be in [0.05, 0.95]")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="atlasforge",
        description="Generate a procedural fantasy world and render it as an "
        "interactive single-file HTML map.",
    )
    p.add_argument("--seed", type=int, default=None,
                   help="world seed (default: random)")
    p.add_argument("--width", type=positive_int(1024), default=160,
                   help="grid width in cells (16-1024, default 160)")
    p.add_argument("--height", type=positive_int(1024), default=160,
                   help="grid height in cells (16-1024, default 160)")
    p.add_argument("--land", type=land_fraction, default=0.38, metavar="FRAC",
                   help="target land fraction 0.05-0.95 (default 0.38)")
    p.add_argument("-o", "--output", default="world.html",
                   help="output HTML path (default world.html)")
    p.add_argument("--json", metavar="PATH", default=None,
                   help="also export full world data as JSON")
    p.add_argument("--title", default=None, help="map title override")
    p.add_argument("--no-settlements", action="store_true",
                   help="skip settlement placement")
    p.add_argument("--quiet", action="store_true", help="suppress progress output")
    p.add_argument("--version", action="version", version=f"atlasforge {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1 << 31)

    def say(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    t0 = time.time()
    say(f"⬢ atlasforge: generating world (seed={seed}, {args.width}x{args.height})")
    try:
        world = generate(
            seed=seed,
            width=args.width,
            height=args.height,
            land_fraction=args.land,
            with_settlements=not args.no_settlements,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    stats = world_stats(world)
    say(
        f"  land {stats['land_pct']}% · {stats['rivers']} rivers · "
        f"{len(stats['biomes'])} biomes · {len(world.settlements)} settlements"
    )
    try:
        write_html(world, args.output, title=args.title)
    except OSError as exc:
        print(f"error: cannot write {args.output!r}: {exc}", file=sys.stderr)
        return 2
    say(f"  wrote {args.output}")
    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(world_to_dict(world), f)
        except OSError as exc:
            print(f"error: cannot write {args.json!r}: {exc}", file=sys.stderr)
            return 2
        say(f"  wrote {args.json}")
    say(f"  done in {time.time() - t0:.1f}s — open {args.output} in a browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
