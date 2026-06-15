"""Command-line interface for Quorum.

Subcommands:
  run        Spin up a healthy cluster, propose writes, show convergence.
  chaos      Run randomized fault-injection across one or many seeds.
  scenario   Run a built-in named scenario (scripted faults).
  dashboard  Live ASCII animation of a cluster under chaos.
  demo       End-to-end tour of every feature.
"""

from __future__ import annotations

import argparse
import sys

from .cluster import Cluster
from .raft import Config, Role
from .network import NetConfig
from .faults import run_chaos
from .linearizer import LinearizabilityChecker, history_from_ops
from . import scenario as scen


# --------------------------------------------------------------------------- #
# Pretty helpers
# --------------------------------------------------------------------------- #
ROLE_GLYPH = {Role.LEADER: "L", Role.CANDIDATE: "C", Role.FOLLOWER: "f"}
GREEN = "\033[32m"; RED = "\033[31m"; YELLOW = "\033[33m"
CYAN = "\033[36m"; DIM = "\033[2m"; BOLD = "\033[1m"; RESET = "\033[0m"


def _c(s, color, enable=True):
    return f"{color}{s}{RESET}" if enable else str(s)


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def cmd_run(args):
    cluster = Cluster(n=args.nodes, seed=args.seed)
    cluster.run(args.warmup)
    leader = cluster.leader()
    print(f"Elected leader: node {leader} (term {cluster.nodes[leader].current_term})"
          if leader is not None else "No leader yet")
    for i in range(args.writes):
        op = cluster.client_request(("put", f"key{i}", i * 10))
        cluster.run(8)
    cluster.run_until_quiescent()
    s = cluster.summary()
    print(f"\nAfter {s['ops_committed']}/{s['ops_total']} writes committed at "
          f"t={s['time']}:")
    leader = cluster.leader()
    print(f"  leader = node {leader}, term {s['term']}")
    for nid in sorted(cluster.alive):
        kv = cluster.kv_snapshot(nid)
        print(f"  node {nid}: commit={cluster.nodes[nid].commit_index:3d} "
              f"kv={kv}")
    stores = [tuple(sorted(cluster.kv_snapshot(i).items())) for i in cluster.alive]
    agree = len(set(stores)) == 1
    print("\n" + _c("✓ all replicas agree", GREEN) if agree
          else _c("✗ replicas diverged", RED))
    return 0 if agree else 1


# --------------------------------------------------------------------------- #
# chaos
# --------------------------------------------------------------------------- #
def cmd_chaos(args):
    seeds = range(args.seed, args.seed + args.runs)
    fails = 0
    print(f"{BOLD}Quorum chaos: {args.runs} run(s), {args.nodes} nodes, "
          f"{args.ticks} ticks each{RESET}")
    print(f"{DIM}loss={args.loss} dup={args.dup}{RESET}\n")
    header = f"{'seed':>5} {'ticks':>6} {'faults':>7} {'ops':>10} {'safety':>8} {'linz':>6}"
    print(header)
    print("-" * len(header))
    for seed in seeds:
        r = run_chaos(seed=seed, n=args.nodes, ticks=args.ticks,
                      loss_prob=args.loss, dup_prob=args.dup)
        safe = _c("OK", GREEN) if r.safety_ok else _c("VIOLATED", RED)
        linz = _c("OK", GREEN) if r.linearizable else _c("BAD", RED)
        ok = r.safety_ok and r.linearizable
        if not ok:
            fails += 1
        print(f"{seed:>5} {r.ticks:>6} {r.faults_injected:>7} "
              f"{r.ops_committed:>4}/{r.ops_total:<5} "
              f"{safe:>{8+len(GREEN)+len(RESET)}} {linz:>{6+len(GREEN)+len(RESET)}}")
        if not ok:
            print(f"      {_c('→ ' + str(r.violation), RED)}")
    print()
    if fails == 0:
        print(_c(f"✓ all {args.runs} runs upheld every safety invariant and a "
                 f"linearizable history", GREEN))
        return 0
    print(_c(f"✗ {fails}/{args.runs} runs FAILED", RED))
    return 1


# --------------------------------------------------------------------------- #
# scenario
# --------------------------------------------------------------------------- #
def cmd_scenario(args):
    if args.name not in scen.SCENARIOS:
        print(f"Unknown scenario '{args.name}'. Available: "
              f"{', '.join(scen.SCENARIOS)}")
        return 2
    result = scen.run_scenario(args.name, verbose=True)
    print()
    if result["safety_ok"] and result["linearizable"]:
        print(_c(f"✓ scenario '{args.name}' passed "
                 f"({result['ops_committed']}/{result['ops_total']} ops committed)",
                 GREEN))
        return 0
    print(_c(f"✗ scenario '{args.name}' FAILED: {result['violation']}", RED))
    return 1


# --------------------------------------------------------------------------- #
# dashboard
# --------------------------------------------------------------------------- #
def cmd_dashboard(args):
    from .dashboard import run_dashboard
    run_dashboard(seed=args.seed, n=args.nodes, ticks=args.ticks,
                  fps=args.fps, chaos=not args.calm)
    return 0


# --------------------------------------------------------------------------- #
# demo
# --------------------------------------------------------------------------- #
def cmd_demo(args):
    print(f"{BOLD}{CYAN}━━━ Quorum: a deterministic Raft consensus simulator ━━━{RESET}\n")

    print(f"{BOLD}1) Leader election + log replication{RESET}")
    cluster = Cluster(n=5, seed=3)
    cluster.run(25)
    print(f"   quiet 5-node cluster elected node {cluster.leader()} "
          f"(term {cluster.nodes[cluster.leader()].current_term})")
    for i in range(4):
        cluster.client_request(("put", f"x{i}", i)); cluster.run(6)
    cluster.run_until_quiescent()
    print(f"   replicated {cluster.summary()['ops_committed']} writes to all nodes; "
          f"every replica's kv = {cluster.kv_snapshot(cluster.leader())}")

    print(f"\n{BOLD}2) Surviving a network partition{RESET}")
    leader = cluster.leader()
    minority = {leader, (leader + 1) % 5}
    majority = set(range(5)) - minority
    cluster.partition([minority, majority])
    print(f"   cut: old leader {leader} isolated with {sorted(minority)}; "
          f"majority {sorted(majority)} must elect a new leader")
    cluster.run(60)
    cluster.client_request(("put", "during_partition", 999))
    cluster.run(20)
    newl = [n for n in majority if cluster.nodes[n].role == Role.LEADER]
    print(f"   majority elected new leader: node {newl[0] if newl else '?'} "
          f"(term {cluster.nodes[newl[0]].current_term if newl else '?'})")
    cluster.heal()
    cluster.run_until_quiescent()
    print(f"   healed; cluster re-converged, kv now = "
          f"{cluster.kv_snapshot(cluster.leader())}")

    print(f"\n{BOLD}3) Randomized chaos with live safety monitoring{RESET}")
    r = run_chaos(seed=42, ticks=1200)
    print(f"   seed 42: {r.faults_injected} faults injected over {r.ticks} ticks, "
          f"{r.ops_committed}/{r.ops_total} ops committed")
    print(f"   safety invariants: {_c('UPHELD', GREEN) if r.safety_ok else _c('VIOLATED', RED)}"
          f"   |   client history: "
          f"{_c('LINEARIZABLE', GREEN) if r.linearizable else _c('NON-LINEARIZABLE', RED)}")

    print(f"\n{BOLD}4) Determinism: same seed replays identically{RESET}")
    a = run_chaos(seed=99, ticks=400); b = run_chaos(seed=99, ticks=400)
    same = (a.ticks, a.ops_committed, a.ops_total) == (b.ticks, b.ops_committed, b.ops_total)
    print(f"   two runs of seed 99: {'identical' if same else 'DIFFERENT'} "
          f"({a.ops_committed}/{a.ops_total} ops, t={a.ticks})")

    print(f"\n{_c('Run `python3 -m quorum.cli chaos --runs 50` to stress it yourself.', DIM)}")
    return 0


# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(prog="quorum",
                                description="Deterministic Raft consensus simulator")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="healthy cluster: elect + replicate writes")
    r.add_argument("--nodes", type=int, default=5)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--warmup", type=int, default=25)
    r.add_argument("--writes", type=int, default=5)
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("chaos", help="randomized fault-injection torture test")
    c.add_argument("--nodes", type=int, default=5)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--runs", type=int, default=10)
    c.add_argument("--ticks", type=int, default=1000)
    c.add_argument("--loss", type=float, default=0.05)
    c.add_argument("--dup", type=float, default=0.03)
    c.set_defaults(func=cmd_chaos)

    s = sub.add_parser("scenario", help="run a named scripted scenario")
    s.add_argument("name")
    s.set_defaults(func=cmd_scenario)

    d = sub.add_parser("dashboard", help="live ASCII cluster animation")
    d.add_argument("--nodes", type=int, default=5)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--ticks", type=int, default=600)
    d.add_argument("--fps", type=float, default=12.0)
    d.add_argument("--calm", action="store_true", help="no fault injection")
    d.set_defaults(func=cmd_dashboard)

    de = sub.add_parser("demo", help="end-to-end tour of every feature")
    de.set_defaults(func=cmd_demo)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
