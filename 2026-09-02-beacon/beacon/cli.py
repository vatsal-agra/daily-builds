"""Command-line entry point: `python3 -m beacon.cli <command> ...`"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict

from . import metrics
from .lidar import LidarSpec
from .pf_localizer import ObservationModel
from .robot import MotionNoise
from .slam import SlamConfig, SlamRun
from .world import BUILTIN_WORLDS


class CliError(Exception):
    """A user-facing input problem -- reported as a clean one-line message,
    not a Python traceback."""


def _build_config(args) -> SlamConfig:
    if args.particles < 4:
        raise CliError(f"--particles must be at least 4 (got {args.particles})")
    if args.resolution <= 0:
        raise CliError(f"--resolution must be positive (got {args.resolution})")
    if args.df_every < 1:
        raise CliError(f"--df-every must be at least 1 (got {args.df_every})")
    if getattr(args, "max_steps", 1) < 1:
        raise CliError(f"--max-steps must be at least 1 (got {args.max_steps})")

    kwargs = dict(
        world_name=args.world,
        resolution=args.resolution,
        num_particles=args.particles,
        df_every=args.df_every,
        seed=args.seed,
        mode=args.mode,
    )
    if args.mode == "waypoints":
        pts = []
        for pair in args.waypoints or []:
            parts = pair.split(",")
            if len(parts) != 2:
                raise CliError(f"--waypoint expects 'X,Y' (got {pair!r})")
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                raise CliError(f"--waypoint expects numeric X,Y (got {pair!r})") from None
        if not pts:
            raise CliError("--mode waypoints needs at least one --waypoint X,Y")
        kwargs["waypoints"] = tuple(pts)
    return SlamConfig(**kwargs)


def _report(run: SlamRun, cfg: SlamConfig) -> dict:
    true_pose = run.robot.pose
    est_pose = run.pf.estimate()
    truth_grid = metrics.ground_truth_grid(run.world, cfg.resolution)
    iou, acc = metrics.map_quality(run.grid, truth_grid)
    return {
        "world": cfg.world_name,
        "mode": cfg.mode,
        "steps": len(run.frames),
        "final_pose_error_m": round(metrics.final_pose_error(true_pose, est_pose), 3),
        "pose_rmse_m": round(metrics.pose_rmse(run.true_poses, run.est_poses), 3),
        "map_iou": round(iou, 3),
        "map_cell_accuracy": round(acc, 3),
        "explored_fraction": round(metrics.explored_fraction(run.grid), 3),
        "goals_reached": run.goals_reached,
        "exploration_done": run.exploration_done,
    }


def cmd_run(args) -> int:
    cfg = _build_config(args)
    t0 = time.time()
    run = SlamRun(cfg).run(max_steps=args.max_steps)
    elapsed = time.time() - t0
    report = _report(run, cfg)
    report["elapsed_s"] = round(elapsed, 2)
    print(json.dumps(report, indent=2))
    if args.log_out:
        _write_log(run, cfg, args.log_out)
        print(f"frame log written to {args.log_out}", file=sys.stderr)
    return 0


def cmd_demo(args) -> int:
    ok = True
    for world in BUILTIN_WORLDS:
        cfg = SlamConfig(world_name=world, resolution=0.3, num_particles=300, df_every=1, mode="explore", seed=1)
        t0 = time.time()
        run = SlamRun(cfg).run(max_steps=args.max_steps)
        elapsed = time.time() - t0
        report = _report(run, cfg)
        report["elapsed_s"] = round(elapsed, 2)
        print(json.dumps(report))
        if report["pose_rmse_m"] > 1.5:
            print(f"  !! {world}: pose RMSE {report['pose_rmse_m']}m exceeds sanity threshold", file=sys.stderr)
            ok = False
    return 0 if ok else 1


def cmd_viz(args) -> int:
    from . import viz

    cfg = _build_config(args)
    run = SlamRun(cfg).run(max_steps=args.max_steps)
    out_path = viz.render(run, cfg, args.out)
    report = _report(run, cfg)
    print(json.dumps(report, indent=2))
    print(f"visualizer written to {out_path}", file=sys.stderr)
    return 0


def _write_log(run: SlamRun, cfg: SlamConfig, path: str) -> None:
    data = {
        "world": cfg.world_name,
        "frames": [asdict(f) for f in run.frames],
    }
    with open(path, "w") as f:
        json.dump(data, f)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="beacon", description="From-scratch 2D robot SLAM simulator")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--world", choices=sorted(BUILTIN_WORLDS), default="office")
        sp.add_argument("--resolution", type=float, default=0.3)
        sp.add_argument("--particles", type=int, default=300)
        sp.add_argument("--df-every", type=int, default=1, dest="df_every")
        sp.add_argument("--seed", type=int, default=42)
        sp.add_argument("--mode", choices=["explore", "waypoints"], default="explore")
        sp.add_argument("--waypoint", action="append", dest="waypoints", metavar="X,Y")
        sp.add_argument("--max-steps", type=int, default=600, dest="max_steps")

    p_run = sub.add_parser("run", help="run one SLAM session and print a metrics report")
    common(p_run)
    p_run.add_argument("--log-out", dest="log_out", help="write the full per-frame run log as JSON")
    p_run.set_defaults(func=cmd_run)

    p_demo = sub.add_parser("demo", help="run all three built-in maps and sanity-check them")
    p_demo.add_argument("--max-steps", type=int, default=700, dest="max_steps")
    p_demo.set_defaults(func=cmd_demo)

    p_viz = sub.add_parser("viz", help="run a session and write a self-contained HTML replay viewer")
    common(p_viz)
    p_viz.add_argument("--out", default="beacon_run.html")
    p_viz.set_defaults(func=cmd_viz)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
