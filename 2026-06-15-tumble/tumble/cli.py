"""Command line interface:  python -m tumble <command> ...

  scenes                          list preset scenes
  sim   --scene NAME [--steps N]  run headless, print diagnostics
  render --scene NAME [--steps N] --out FILE.svg   snapshot to SVG
  check                           run physics invariants, report pass/fail
"""
import argparse
import sys

from . import scenes
from .engine import World
from .render_svg import render


def _load(scene, file):
    if file:
        with open(file) as f:
            return World.from_json(f.read())
    return scenes.build(scene)


def cmd_scenes(args):
    for name in scenes.names():
        w = scenes.build(name)
        print("  %-11s  %3d particles  %3d constraints  %d segments"
              % (name, len(w.particles), len(w.constraints), len(w.segments)))
    return 0


def cmd_sim(args):
    w = _load(args.scene, args.file)
    print("scene: %s   particles=%d constraints=%d segments=%d  iters=%d"
          % (args.scene or args.file, len(w.particles), len(w.constraints),
             len(w.segments), w.iterations))
    for step in range(args.steps):
        w.step()
        if args.verbose and (step % max(1, args.steps // 10) == 0):
            print("  step %5d  KE=%12.3f  active_constraints=%d  finite=%s"
                  % (step, w.kinetic_energy(), w.active_constraints(),
                     w.all_finite()))
    print("done %d steps:  KE=%.3f  active_constraints=%d/%d  finite=%s"
          % (args.steps, w.kinetic_energy(), w.active_constraints(),
             len(w.constraints), w.all_finite()))
    if args.out:
        with open(args.out, "w") as f:
            f.write(w.to_json(indent=2))
        print("wrote final state -> %s" % args.out)
    return 0


def cmd_render(args):
    w = _load(args.scene, args.file)
    for _ in range(args.steps):
        w.step()
    svg = render(w)
    with open(args.out, "w") as f:
        f.write(svg)
    print("rendered %s after %d steps -> %s" % (args.scene or args.file,
                                                args.steps, args.out))
    return 0


def cmd_check(args):
    """Quick physics invariants across all scenes."""
    ok = True
    for name in scenes.names():
        w = scenes.build(name)
        c0 = w.active_constraints()
        for _ in range(400):
            w.step()
        finite = w.all_finite()
        # nothing escaped the world bounds (allow a hair of tolerance)
        escaped = any(p.x < -1 or p.x > w.width + 1 or p.y < -1
                      or p.y > w.height + 1 for p in w.particles)
        status = "ok" if (finite and not escaped) else "FAIL"
        if not (finite and not escaped):
            ok = False
        print("  %-11s  finite=%-5s escaped=%-5s constraints %d->%d   [%s]"
              % (name, finite, escaped, c0, w.active_constraints(), status))
    print("ALL OK" if ok else "FAILURES DETECTED")
    return 0 if ok else 1


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="tumble", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("scenes", help="list preset scenes")
    sp.set_defaults(func=cmd_scenes)

    sp = sub.add_parser("sim", help="run a scene headless")
    sp.add_argument("--scene", default="cloth")
    sp.add_argument("--file", help="load a scene JSON instead of a preset")
    sp.add_argument("--steps", type=int, default=300)
    sp.add_argument("--out", help="write final state JSON here")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_sim)

    sp = sub.add_parser("render", help="render a scene to SVG after N steps")
    sp.add_argument("--scene", default="cloth")
    sp.add_argument("--file", help="load a scene JSON instead of a preset")
    sp.add_argument("--steps", type=int, default=120)
    sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("check", help="run physics invariants on all scenes")
    sp.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
