"""Command-line interface: `orrery run|bench|resume|info|demo`."""

import argparse
import os
import sys

from . import scenarios
from . import report
from . import kepler
from . import octree
from . import bruteforce
from . import integrator
from .body import Body
from .vector import Vec3
from .simulation import Simulation


def _build_scenario(args):
    kwargs = {}
    if args.scenario == "plummer_cluster":
        if args.n is not None:
            kwargs["n"] = args.n
        if args.seed is not None:
            kwargs["seed"] = args.seed
    elif args.scenario == "galaxy_collision":
        if args.n is not None:
            kwargs["n_per_galaxy"] = args.n
        if args.seed is not None:
            kwargs["seed"] = args.seed
    return scenarios.build(args.scenario, **kwargs)


def cmd_run(args):
    sc = _build_scenario(args)
    dt = args.dt if args.dt is not None else sc.recommended_dt
    softening = args.softening if args.softening is not None else sc.softening

    sim = Simulation.from_scenario(
        sc, method=args.method, theta=args.theta,
        use_barnes_hut=not args.bruteforce, collisions=args.collisions,
        softening=softening,
    )

    print(f"Scenario: {sc.name} ({len(sc.bodies)} bodies)")
    print(f"  {sc.description}")
    engine = "brute force" if args.bruteforce else f"Barnes-Hut theta={args.theta}"
    print(f"  steps={args.steps} dt={dt:.6g} method={args.method} engine={engine} softening={softening:.4g}")

    try:
        history = sim.run(args.steps, dt, record_every=args.record_every)
    except FloatingPointError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    e0, e1 = history[0]["energy"], history[-1]["energy"]
    drift = abs((e1 - e0) / e0) if e0 != 0 else abs(e1 - e0)
    print(f"  t_final={sim.t:.6g}  energy: start={e0:.6e} end={e1:.6e} drift={drift:.3e}")
    if sim.collision_log:
        print(f"  collisions: {len(sim.collision_log)} merge event(s)")

    if args.out:
        sim.save(args.out)
        print(f"  checkpoint saved -> {args.out}")
    if args.report:
        report.write_trajectory_report(history, sc.name, sc.description, args.report)
        print(f"  trajectory report -> {args.report}")
    return 0


def cmd_resume(args):
    try:
        sim = Simulation.load(args.checkpoint)
    except (OSError, ValueError, KeyError) as e:
        print(f"ERROR: could not load checkpoint {args.checkpoint!r}: {e}", file=sys.stderr)
        return 1

    print(f"Resuming {args.checkpoint}: t={sim.t:.6g}, step={sim.step_count}, {len(sim.bodies)} bodies")
    dt = args.dt if args.dt is not None else 1e-3
    try:
        history = sim.run(args.steps, dt, record_every=args.record_every)
    except FloatingPointError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"  ran {args.steps} more steps -> t={sim.t:.6g}")
    if args.out:
        sim.save(args.out)
        print(f"  checkpoint saved -> {args.out}")
    if args.report:
        report.write_trajectory_report(history, "resumed", f"Resumed from {args.checkpoint}", args.report)
        print(f"  trajectory report -> {args.report}")
    return 0


def cmd_bench(args):
    try:
        ns = tuple(int(x) for x in args.ns.split(","))
        thetas = tuple(float(x) for x in args.thetas.split(","))
    except ValueError:
        print("ERROR: --ns and --thetas must be comma-separated numbers", file=sys.stderr)
        return 1

    results = report.run_benchmark(ns=ns, thetas=thetas)
    report.render_benchmark_html(results, args.out)
    print(f"Benchmark report -> {args.out}")
    for r in results["timing"]:
        speedup = r["bruteforce_s"] / max(r["barnes_hut_s"], 1e-9)
        print(f"  N={r['n']:5d}  bruteforce={r['bruteforce_s']*1000:9.3f}ms  "
              f"barnes-hut={r['barnes_hut_s']*1000:9.3f}ms  speedup={speedup:5.2f}x")
    return 0


def cmd_info(args):
    print("Available scenarios:")
    for name in sorted(scenarios.REGISTRY):
        sc = scenarios.build(name)
        print(f"  {name:18s} {len(sc.bodies):4d} bodies   G={sc.G:.6g}   recommended dt~{sc.recommended_dt:.4g}")
        print(f"    {sc.description}")
    return 0


def cmd_demo(args):
    """A self-checking walkthrough: exercises every required feature and
    prints PASS/FAIL for each, exiting non-zero if anything fails. Also
    writes trajectory + benchmark reports to --outdir.
    """
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    failures = []

    def check(label, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {label}{'  ' + detail if detail else ''}")
        if not cond:
            failures.append(label)

    print("== 1. Barnes-Hut vs brute force ==")
    import random as _random
    rng = _random.Random(1)
    bodies = [
        Body(f"b{i}", rng.uniform(0.5, 2.0),
             Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), Vec3(0, 0, 0))
        for i in range(40)
    ]
    a_bf = bruteforce.compute_accelerations(bodies, G=1.0, softening=0.01)
    a_theta0 = octree.compute_accelerations(bodies, G=1.0, theta=0.0, softening=0.01)
    max_err = max((a - b).norm() for a, b in zip(a_bf, a_theta0))
    check("theta=0 Barnes-Hut matches brute force", max_err < 1e-9, f"max abs err={max_err:.2e}")

    a_theta = octree.compute_accelerations(bodies, G=1.0, theta=0.5, softening=0.01)
    rel_errs = [(a - b).norm() / max(a.norm(), 1e-12) for a, b in zip(a_bf, a_theta)]
    check("theta=0.5 Barnes-Hut is a close approximation", max(rel_errs) < 0.15, f"max rel err={max(rel_errs):.3f}")

    print("== 2. Symplectic leapfrog vs explicit Euler energy conservation ==")
    mu = scenarios.G_ASTRO * 1.0
    a, e = 1.0, 0.5
    pos, vel = kepler.elements_to_state(a, e, 0, 0, 0, 0, t=0.0, mu=mu)
    period = kepler.orbital_period(a, mu)
    dt = period / 2000.0

    sim_lf = Simulation(
        [Body("Sun", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)), Body("P", 1e-8, pos, vel)],
        G=scenarios.G_ASTRO, method="leapfrog", use_barnes_hut=False, softening=1e-6,
    )
    e_lf_0 = integrator.total_energy(sim_lf.bodies, sim_lf.G, sim_lf.softening)
    sim_lf.run(4000, dt)
    e_lf_1 = integrator.total_energy(sim_lf.bodies, sim_lf.G, sim_lf.softening)
    lf_drift = abs((e_lf_1 - e_lf_0) / e_lf_0)
    check("leapfrog energy drift over 2 orbits is tiny", lf_drift < 1e-6, f"drift={lf_drift:.2e}")

    sim_eu = Simulation(
        [Body("Sun", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)), Body("P", 1e-8, pos, vel)],
        G=scenarios.G_ASTRO, method="euler", use_barnes_hut=False, softening=1e-6,
    )
    e_eu_0 = integrator.total_energy(sim_eu.bodies, sim_eu.G, sim_eu.softening)
    sim_eu.run(4000, dt)
    e_eu_1 = integrator.total_energy(sim_eu.bodies, sim_eu.G, sim_eu.softening)
    eu_drift = abs((e_eu_1 - e_eu_0) / e_eu_0)
    check("explicit Euler visibly leaks energy (demonstrating why it's wrong)", eu_drift > 0.05, f"drift={eu_drift:.2e}")
    check("leapfrog conserves energy far better than Euler on the same orbit", lf_drift < eu_drift / 1000, f"leapfrog={lf_drift:.2e} vs euler={eu_drift:.2e}")

    print("== 3. Kepler analytic oracle vs N-body integration ==")
    sim_ok = Simulation(
        [Body("Sun", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)), Body("P", 1e-8, pos, vel)],
        G=scenarios.G_ASTRO, method="leapfrog", use_barnes_hut=False, softening=1e-6,
    )
    planet = sim_ok.bodies[1]
    max_pos_err = 0.0
    for _ in range(2000):
        sim_ok.step(dt)
        analytic_pos, _ = kepler.elements_to_state(a, e, 0, 0, 0, 0, t=sim_ok.t, mu=mu)
        max_pos_err = max(max_pos_err, (planet.position - analytic_pos).norm())
    check("N-body orbit tracks the analytic Kepler ellipse over 1 period", max_pos_err < 0.01 * a, f"max pos err={max_pos_err:.2e} (orbit scale a={a})")

    print("== 4. Figure-eight three-body choreography closes on itself ==")
    sc8 = scenarios.figure_eight()
    sim8 = Simulation.from_scenario(sc8, method="leapfrog", use_barnes_hut=False)
    start = [b.position.copy() for b in sim8.bodies]
    steps8 = 4000
    dt8 = 6.32591398 / steps8
    history8 = sim8.run(steps8, dt8, record_every=max(1, steps8 // 400))
    return_err = max((b.position - s).norm() for b, s in zip(sim8.bodies, start))
    check("figure-eight returns close to its start after one period", return_err < 1e-3, f"return err={return_err:.2e}")
    report.write_trajectory_report(history8, "figure_eight", sc8.description, os.path.join(outdir, "figure_eight.html"))

    print("== 5. Collision/accretion conserves momentum ==")
    b1 = Body("A", 1.0, Vec3(-1, 0, 0), Vec3(1, 0, 0), radius=0.5)
    b2 = Body("B", 1.0, Vec3(1, 0, 0), Vec3(-1, 0, 0), radius=0.5)
    p_before = b1.momentum() + b2.momentum()
    sim_c = Simulation([b1, b2], G=0.0, method="leapfrog", use_barnes_hut=False, collisions=True, softening=0.01)
    sim_c.run(60, 0.02)
    alive = [b for b in sim_c.bodies if b.alive]
    p_after = Vec3(0, 0, 0)
    for b in sim_c.bodies:
        if b.alive:
            p_after += b.momentum()
    check("colliding bodies merge into one", len(alive) == 1, f"alive={[b.name for b in alive]}")
    check("merge conserves total momentum", (p_after - p_before).norm() < 1e-9, f"before={p_before.to_tuple()} after={p_after.to_tuple()}")

    print("== 6. Full scenario runs + reports ==")
    for name in ("solar_system", "binary_star", "plummer_cluster"):
        sc = scenarios.build(name)
        sim = Simulation.from_scenario(sc, method="leapfrog", theta=0.5, use_barnes_hut=True)
        steps = 800 if name != "plummer_cluster" else 300
        hist = sim.run(steps, sc.recommended_dt, record_every=max(1, steps // 300))
        out = os.path.join(outdir, f"{name}.html")
        report.write_trajectory_report(hist, name, sc.description, out)
        check(f"{name} ran {steps} steps and wrote a report", os.path.exists(out), out)

    print("== 7. Barnes-Hut benchmark report ==")
    results = report.run_benchmark(ns=(10, 30, 100), thetas=(0.0, 0.5, 1.0))
    bench_out = os.path.join(outdir, "benchmark.html")
    report.render_benchmark_html(results, bench_out)
    check("benchmark report written", os.path.exists(bench_out), bench_out)

    print()
    if failures:
        print(f"DEMO FAILED: {len(failures)} check(s) failed: {failures}")
        return 1
    print("DEMO OK: all checks passed.")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="orrery", description="A from-scratch gravitational N-body simulator.")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="run a scenario")
    pr.add_argument("--scenario", default="solar_system", choices=sorted(scenarios.REGISTRY))
    pr.add_argument("--steps", type=int, default=1000)
    pr.add_argument("--dt", type=float, default=None)
    pr.add_argument("--method", choices=["leapfrog", "euler"], default="leapfrog")
    pr.add_argument("--theta", type=float, default=0.5)
    pr.add_argument("--bruteforce", action="store_true", help="use O(N^2) direct summation instead of Barnes-Hut")
    pr.add_argument("--softening", type=float, default=None)
    pr.add_argument("--collisions", action="store_true")
    pr.add_argument("--record-every", type=int, default=1)
    pr.add_argument("--n", type=int, default=None, help="body count, for plummer_cluster/galaxy_collision")
    pr.add_argument("--seed", type=int, default=None)
    pr.add_argument("--out", default=None, help="save a JSON checkpoint")
    pr.add_argument("--report", default=None, help="write an interactive HTML trajectory report")
    pr.set_defaults(func=cmd_run)

    pres = sub.add_parser("resume", help="resume a checkpoint")
    pres.add_argument("checkpoint")
    pres.add_argument("--steps", type=int, default=1000)
    pres.add_argument("--dt", type=float, default=None)
    pres.add_argument("--record-every", type=int, default=1)
    pres.add_argument("--out", default=None)
    pres.add_argument("--report", default=None)
    pres.set_defaults(func=cmd_resume)

    pb = sub.add_parser("bench", help="Barnes-Hut vs brute-force benchmark")
    pb.add_argument("--ns", default="10,30,100,300")
    pb.add_argument("--thetas", default="0.0,0.3,0.5,0.8,1.2")
    pb.add_argument("--out", default="benchmark.html")
    pb.set_defaults(func=cmd_bench)

    pi = sub.add_parser("info", help="list available scenarios")
    pi.set_defaults(func=cmd_info)

    pd = sub.add_parser("demo", help="self-checking end-to-end walkthrough")
    pd.add_argument("--outdir", default="demo_output")
    pd.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
