"""Skein CLI.

    skein sim [--sites N] [--edits N] [--seed N] [--drop P] [--dup P]
    skein chaos [--trials N] [--seed N]
    skein shuffle-proof [--trials N] [--seed N] [--edits N]
    skein demo
"""

from __future__ import annotations

import argparse
import random
import sys

from . import convergence
from .simulate import Simulation


class SkeinCliError(ValueError):
    """Raised for bad CLI input; caught by main() and reported as a
    clean one-line error instead of a raw traceback."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SkeinCliError(message)


def cmd_sim(args: argparse.Namespace) -> int:
    _require(args.sites >= 2, f"--sites must be at least 2 (a single site has no one to collaborate with), got {args.sites}")
    _require(args.edits >= 0, f"--edits must be >= 0, got {args.edits}")
    _require(0.0 <= args.drop <= 1.0, f"--drop must be a probability in [0, 1], got {args.drop}")
    _require(0.0 <= args.dup <= 1.0, f"--dup must be a probability in [0, 1], got {args.dup}")

    site_ids = [f"site{i}" for i in range(args.sites)]
    sim = Simulation(site_ids, seed=args.seed, drop_prob=args.drop, dup_prob=args.dup)
    rng = random.Random(args.seed)
    print(f"# Simulating {args.sites} sites, {args.edits} edits, seed={args.seed}, drop={args.drop}, dup={args.dup}")
    for _ in range(args.edits):
        sim.step()
        if args.partitions and rng.random() < 0.08:
            v = rng.choice(site_ids)
            sim.partition(v)
            print(f"  [tick {sim.network.tick_no}] network PARTITIONS {v}")
        if args.partitions and rng.random() < 0.08:
            v = rng.choice(site_ids)
            sim.heal(v)
            print(f"  [tick {sim.network.tick_no}] network HEALS {v}")
        op = sim.random_edit()
        print(f"  [tick {sim.network.tick_no}] {op}")
    sim.heal_all()
    delivered = sim.drain()
    print(f"# Drained network: {delivered} messages delivered")
    print(f"# Network stats: {sim.network.stats}")
    for sid, text in sim.texts().items():
        print(f"  {sid}: {text!r}")
    if sim.converged():
        print("# CONVERGED — every site holds an identical document.")
        return 0
    print("# DID NOT CONVERGE — this is a bug.")
    return 1


def cmd_chaos(args: argparse.Namespace) -> int:
    _require(args.trials >= 1, f"--trials must be >= 1, got {args.trials}")
    print(f"# Running {args.trials} randomized chaos trials (seed_base={args.seed})...")
    result = convergence.run_many_chaos_trials(trials=args.trials, seed_base=args.seed)
    if result["ok"]:
        print(f"# ALL {result['trials']} trials converged and matched the independent oracle.")
        return 0
    print(f"# {len(result['failures'])}/{result['trials']} trials FAILED:")
    for f in result["failures"][:5]:
        print(f"  seed={f['seed']} texts={f['texts']} expected={f['expected']!r} pending={f['pending_sites']}")
    return 1


def cmd_shuffle_proof(args: argparse.Namespace) -> int:
    _require(args.trials >= 1, f"--trials must be >= 1, got {args.trials}")
    _require(args.edits >= 1, f"--edits must be >= 1 (need at least one op to shuffle), got {args.edits}")
    site_ids = [f"site{i}" for i in range(3)]
    sim = Simulation(site_ids, seed=args.seed)
    for _ in range(args.edits):
        sim.random_edit()
    print(
        f"# Generated {len(sim.all_ops)} ops across {len(site_ids)} sites "
        f"(oracle text: {convergence.compute_oracle_text(sim.all_ops)!r})"
    )
    print(f"# Replaying that exact op set through {args.trials} independent random delivery orders...")
    result = convergence.random_shuffles_converge(sim.all_ops, trials=args.trials, seed=args.seed)
    if result["ok"]:
        print(f"# ALL {result['trials']} random delivery orders converged to the identical document.")
        return 0
    print(f"# {len(result['mismatches'])} MISMATCHES found:")
    for m in result["mismatches"][:5]:
        print(f"  trial={m['trial']} got={m['got']!r} expected={m['expected']!r}")
    return 1


def cmd_demo(args: argparse.Namespace) -> int:
    print("=== Skein demo ===\n")
    print("-- 1. Two sites type at the same position at the same time --")
    sim = Simulation(["alice", "bob"], seed=42)
    sim.type_str("alice", 0, "hello")
    sim.drain()
    print(f"  after 'hello' propagates: alice={sim.sites['alice'].text!r} bob={sim.sites['bob'].text!r}")
    sim.type_at("alice", 5, "!")  # not yet delivered to bob
    sim.type_at("bob", 5, "?")  # concurrent insert at the exact same position
    print("  concurrently, alice types '!' and bob types '?' at the same position (not yet delivered)")
    sim.drain()
    print(f"  after delivery: alice={sim.sites['alice'].text!r} bob={sim.sites['bob'].text!r}")
    assert sim.sites["alice"].text == sim.sites["bob"].text, "convergence failed!"
    print(f"  -> converged to the identical document without any coordination: {sim.sites['alice'].text!r}\n")

    print("-- 2. A partitioned site keeps editing, then reconnects --")
    sim2 = Simulation(["a", "b", "c"], seed=7)
    sim2.type_str("a", 0, "the quick fox")
    sim2.drain()
    sim2.partition("c")
    sim2.type_str("a", 4, "brown ")
    sim2.drain()
    sim2.type_str("c", 13, " jumps")  # c is offline, editing its own stale copy
    print(f"  while c is partitioned: a={sim2.sites['a'].text!r} c={sim2.sites['c'].text!r}")
    sim2.heal("c")
    sim2.drain()
    print(f"  after c reconnects: a={sim2.sites['a'].text!r} b={sim2.sites['b'].text!r} c={sim2.sites['c'].text!r}")
    assert sim2.converged(), "convergence failed after heal!"
    print(f"  -> all three converged: {sim2.sites['a'].text!r}\n")

    print("-- 3. Convergence proof: 30 random chaos trials --")
    result = convergence.run_many_chaos_trials(trials=30, seed_base=1000)
    print(f"  {result['trials'] - len(result['failures'])}/{result['trials']} trials converged and matched the independent oracle")
    if not result["ok"]:
        print("  FAILURES:", result["failures"][:3])
        return 1

    print("\n-- 4. Order-independence proof: one op set, 50 random delivery orders --")
    sim3 = Simulation(["x", "y", "z"], seed=99)
    for _ in range(40):
        sim3.random_edit()
    shuffle_result = convergence.random_shuffles_converge(sim3.all_ops, trials=50, seed=99)
    print(
        f"  {shuffle_result['trials'] - len(shuffle_result['mismatches'])}/{shuffle_result['trials']} "
        f"random orders converged to {shuffle_result['baseline']!r}"
    )
    if not shuffle_result["ok"]:
        return 1

    print("\n=== All demo checks passed. ===")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skein", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("sim", help="run one multi-site chaos simulation and print the transcript")
    sp.add_argument("--sites", type=int, default=3)
    sp.add_argument("--edits", type=int, default=40)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--drop", type=float, default=0.05)
    sp.add_argument("--dup", type=float, default=0.05)
    sp.add_argument("--no-partitions", dest="partitions", action="store_false")
    sp.set_defaults(func=cmd_sim, partitions=True)

    cp = sub.add_parser("chaos", help="run many randomized chaos trials and report pass/fail")
    cp.add_argument("--trials", type=int, default=100)
    cp.add_argument("--seed", type=int, default=0)
    cp.set_defaults(func=cmd_chaos)

    up = sub.add_parser("shuffle-proof", help="prove one fixed op set converges under many random delivery orders")
    up.add_argument("--trials", type=int, default=200)
    up.add_argument("--edits", type=int, default=40)
    up.add_argument("--seed", type=int, default=0)
    up.set_defaults(func=cmd_shuffle_proof)

    dp = sub.add_parser("demo", help="run the full narrated demo")
    dp.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SkeinCliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (IndexError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
