"""kinesis CLI: evolve/replay/gallery/demo/test subcommands."""
import argparse
import json
import sys
import time

from .genome import Genome
from .ga import Population
from .simulate import run_simulation

DEFAULT_POP_SIZE = 60
DEFAULT_DURATION = 6.0


class CliError(Exception):
    """A user-facing error (bad path, malformed file) -- caught once in
    main() and printed cleanly instead of surfacing a raw traceback."""


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise CliError(f"file not found: {path}")
    except json.JSONDecodeError as e:
        raise CliError(f"{path} is not valid JSON ({e})")
    except IsADirectoryError:
        raise CliError(f"{path} is a directory, not a file")


def cmd_evolve(args):
    if args.generations <= 0:
        print("error: --generations must be positive", file=sys.stderr)
        return 1
    if args.duration <= 0:
        print("error: --duration must be positive", file=sys.stderr)
        return 1

    if args.resume:
        checkpoint = _load_checkpoint(args.resume)
        pop = Population.from_dict(checkpoint, seed=args.seed)
        if args.pop_size != DEFAULT_POP_SIZE or args.duration != DEFAULT_DURATION:
            print(f"note: --resume continues with the checkpoint's own "
                  f"pop-size={pop.pop_size} / duration={pop.sim_duration}s "
                  f"(--pop-size/--duration are ignored when resuming)")
        print(f"resumed from {args.resume}: generation {pop.generation}, "
              f"{pop.pop_size} individuals, best-so-far={pop.best().fitness:.3f}")
    else:
        if args.pop_size < 4:
            print("error: --pop-size must be at least 4 (tournament size is 4)", file=sys.stderr)
            return 1
        pop = Population(pop_size=args.pop_size, seed=args.seed, sim_duration=args.duration)

    start = time.time()

    def log(h):
        elapsed = time.time() - start
        print(f"gen {h['generation']:4d}  best={h['best']:8.3f}  "
              f"mean={h['mean']:8.3f}  worst={h['worst']:8.3f}  ({elapsed:6.1f}s elapsed)")

    pop.run(args.generations, log=log)
    champ = pop.best()
    print(f"\nchampion: fitness={champ.fitness:.3f} distance={champ.distance:.3f} "
          f"energy={champ.energy:.1f} toppled={champ.toppled} "
          f"nodes={champ.genome.node_count()} depth={champ.genome.depth()}")

    pop.save(args.out)
    print(f"saved population checkpoint -> {args.out}")
    return 0


def _load_checkpoint(path):
    d = _read_json(path)
    if "individuals" not in d or "generation" not in d:
        raise CliError(f"{path} doesn't look like a Kinesis population checkpoint "
                        "(missing 'individuals'/'generation')")
    return d


def _load_bare_genome(path):
    d = _read_json(path)
    try:
        return Genome.from_dict(d)
    except (KeyError, TypeError) as e:
        raise CliError(f"{path} doesn't look like a Kinesis genome file ({e})")


def _write_text(path, content):
    import os
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def cmd_replay(args):
    from . import viz
    if args.genome:
        genome = _load_bare_genome(args.genome)
        label = args.genome
        fitness_hint = None
    else:
        d = _load_checkpoint(args.checkpoint)
        individuals = d["individuals"]
        rank = args.rank
        if rank < 0 or rank >= len(individuals):
            print(f"error: --rank {rank} out of range for population of size {len(individuals)}",
                  file=sys.stderr)
            return 1
        ranked = sorted(individuals, key=lambda ind: ind["fitness"], reverse=True)
        item = ranked[rank]
        genome = Genome.from_dict(item["genome"])
        label = f"{args.checkpoint} (rank {rank}, fitness {item['fitness']:.3f})"
        fitness_hint = item["fitness"]

    result = run_simulation(genome, duration=args.duration, record_trace=True)
    print(f"replayed {label}: distance={result.distance:.3f} energy={result.energy:.1f} "
          f"toppled={result.toppled} fitness={result.fitness:.3f}")
    html = viz.render_replay(genome, result, title=label, fitness_hint=fitness_hint)
    _write_text(args.out, html)
    print(f"wrote replay viewer -> {args.out}")
    return 0


def cmd_gallery(args):
    from . import viz
    d = _load_checkpoint(args.checkpoint)
    html = viz.render_gallery(d, args.checkpoint)
    _write_text(args.out, html)
    print(f"wrote gallery -> {args.out} ({len(d['individuals'])} creatures, "
          f"generation {d['generation']})")
    return 0


def cmd_fitness_chart(args):
    from . import viz
    d = _load_checkpoint(args.checkpoint)
    html = viz.render_fitness_chart(d["history"], args.checkpoint)
    _write_text(args.out, html)
    print(f"wrote fitness chart -> {args.out} ({len(d['history'])} generations)")
    return 0


def cmd_demo(args):
    print("Kinesis demo: evolving a small population for a handful of generations.")
    print("(Use `kinesis evolve --generations 60 --pop-size 80` for a real run.)\n")
    pop = Population(pop_size=16, seed=7, sim_duration=4.0)

    def log(h):
        print(f"  gen {h['generation']:2d}  best={h['best']:7.3f}  mean={h['mean']:7.3f}")

    pop.run(8, log=log)
    champ = pop.best()
    print(f"\nchampion after 8 generations: fitness={champ.fitness:.3f} "
          f"distance={champ.distance:.3f} nodes={champ.genome.node_count()}")

    out_dir = args.out_dir
    import os
    os.makedirs(out_dir, exist_ok=True)
    ckpt_path = os.path.join(out_dir, "demo_population.json")
    pop.save(ckpt_path)

    from . import viz
    result = run_simulation(champ.genome, duration=6.0, record_trace=True)
    replay_html = viz.render_replay(champ.genome, result, title="demo champion",
                                     fitness_hint=champ.fitness)
    replay_path = os.path.join(out_dir, "demo_replay.html")
    with open(replay_path, "w") as f:
        f.write(replay_html)

    gallery_html = viz.render_gallery(pop.to_dict(), "demo")
    gallery_path = os.path.join(out_dir, "demo_gallery.html")
    with open(gallery_path, "w") as f:
        f.write(gallery_html)

    chart_html = viz.render_fitness_chart(pop.history, "demo")
    chart_path = os.path.join(out_dir, "demo_fitness.html")
    with open(chart_path, "w") as f:
        f.write(chart_html)

    print(f"\nwrote: {ckpt_path}, {replay_path}, {gallery_path}, {chart_path}")
    return 0


def cmd_test(args):
    import subprocess
    return subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])


def build_parser():
    p = argparse.ArgumentParser(prog="kinesis", description="Evolving virtual creatures.")
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("evolve", help="run a genetic algorithm evolution")
    pe.add_argument("--generations", type=int, default=40, help="additional generations to run")
    pe.add_argument("--pop-size", type=int, default=DEFAULT_POP_SIZE)
    pe.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                     help="simulated seconds per evaluation")
    pe.add_argument("--seed", type=int, default=None)
    pe.add_argument("--out", default="data/population.json")
    pe.add_argument("--resume", default=None,
                     help="continue evolving from a saved population checkpoint JSON "
                          "instead of starting a fresh random population "
                          "(uses the checkpoint's own pop-size/duration)")
    pe.set_defaults(func=cmd_evolve)

    pr = sub.add_parser("replay", help="render an HTML replay of one creature")
    src = pr.add_mutually_exclusive_group(required=True)
    src.add_argument("--genome", help="path to a single saved genome JSON")
    src.add_argument("--checkpoint", help="path to a population checkpoint JSON")
    pr.add_argument("--rank", type=int, default=0, help="0=best, 1=second best, ... (with --checkpoint)")
    pr.add_argument("--duration", type=float, default=8.0)
    pr.add_argument("--out", default="replay.html")
    pr.set_defaults(func=cmd_replay)

    pg = sub.add_parser("gallery", help="render an HTML gallery of a whole population")
    pg.add_argument("--checkpoint", required=True)
    pg.add_argument("--out", default="gallery.html")
    pg.set_defaults(func=cmd_gallery)

    pf = sub.add_parser("fitness-chart", help="render an HTML fitness-over-generations chart")
    pf.add_argument("--checkpoint", required=True)
    pf.add_argument("--out", default="fitness.html")
    pf.set_defaults(func=cmd_fitness_chart)

    pd = sub.add_parser("demo", help="quick end-to-end demonstration")
    pd.add_argument("--out-dir", default="data")
    pd.set_defaults(func=cmd_demo)

    pt = sub.add_parser("test", help="run the test suite")
    pt.set_defaults(func=cmd_test)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
