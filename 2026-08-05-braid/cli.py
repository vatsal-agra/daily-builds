#!/usr/bin/env python3
"""
Braid CLI — headless multi-peer CRDT simulation, convergence proofs, and
the live collaboration server. No browser required for any subcommand
except `serve` (which is what the browser talks to).

Subcommands:
  simulate   run one seeded chaos simulation and report the result
  sweep      run many seeds back-to-back and report the overall
             convergence rate (the "Strong Eventual Consistency" proof)
  scenario   a scripted, narrated offline/reconnect walkthrough
  serve      start the real-time collaborative web editor
"""

import argparse
import sys

from crdt.network import Simulation
from crdt.site import Site


def cmd_simulate(args):
    sim = Simulation(args.seed, num_sites=args.sites, gossip_every=args.gossip_every)
    result = sim.run(num_ops=args.ops)
    print(f"seed={args.seed} sites={args.sites} ops={args.ops} ticks={result['ticks']}")
    print(f"drop_prob={sim.net.drop_prob} dup_prob={sim.net.dup_prob} "
          f"latency={sim.net.latency_range}")
    print()
    if args.verbose:
        for line in result["history"]:
            print(" ", line)
        print()
    for sid, text in sorted(result["texts"].items()):
        print(f"  site {sid}: {text!r}  (len={len(text)})")
    print()
    if result["converged"]:
        print(f"CONVERGED — all {args.sites} replicas hold the identical document.")
        return 0
    else:
        print("DID NOT CONVERGE:")
        if not result["settled"]:
            print("  - at least one replica still has causally-blocked ops pending")
        texts = set(result["texts"].values())
        print(f"  - {len(texts)} distinct document states across {args.sites} sites")
        return 1


def cmd_sweep(args):
    ok = 0
    failures = []
    for seed in range(args.count):
        sim = Simulation(seed, num_sites=args.sites, gossip_every=args.gossip_every)
        result = sim.run(num_ops=args.ops)
        if result["converged"]:
            ok += 1
        else:
            failures.append(seed)
    print(f"sweep: {ok}/{args.count} seeds converged (sites={args.sites}, ops={args.ops})")
    if failures:
        print(f"FAILING SEEDS: {failures[:20]}{' ...' if len(failures) > 20 else ''}")
        return 1
    print("Strong Eventual Consistency held on every seed in the sweep.")
    return 0


def cmd_scenario(args):
    """A scripted, narrated walkthrough: two peers start in sync, one goes
    offline, both keep editing independently (diverging on purpose), the
    offline peer reconnects, and everything merges back to one document —
    without a server, a lock, or either peer ever "winning"."""

    def say(msg):
        print(msg)

    say("=" * 72)
    say("BRAID SCENARIO: offline editing + reconnect merge")
    say("=" * 72)

    alice = Site("Alice")
    bob = Site("Bob")

    def sync(a, b):
        for op in a.op_log:
            b.receive(op)
        for op in b.op_log:
            a.receive(op)

    for i, ch in enumerate("hello team"):
        alice.type_insert(i, ch)
    sync(alice, bob)
    say(f"\n[both online] Alice types a greeting, Bob is synced:")
    say(f"  Alice: {alice.text()!r}")
    say(f"  Bob:   {bob.text()!r}")
    assert alice.text() == bob.text()

    say("\n>>> Bob's laptop loses network access. No more messages get through. <<<")

    # Bob edits while offline
    bob_len = bob.doc.visible_length()
    bob.type_delete(bob_len - 1)  # delete 'm'
    bob.type_insert(bob.doc.visible_length(), "!")
    say(f"  Bob (offline)  : {bob.text()!r}")

    # Alice edits concurrently, unaware Bob is offline or of Bob's edits
    alice.type_text(0, ">> ")
    alice.type_text(len(alice.text()), " :)")
    say(f"  Alice (online) : {alice.text()!r}")

    say(f"\n  These have now DIVERGED on purpose — Bob's ops never reached")
    say(f"  Alice, and Alice's ops never reached Bob. Neither is 'wrong'.")
    assert alice.text() != bob.text()

    say("\n>>> Bob's network comes back. Both sides exchange every op they missed. <<<")
    sync(alice, bob)

    say(f"\n  Alice: {alice.text()!r}")
    say(f"  Bob:   {bob.text()!r}")
    if alice.text() == bob.text():
        say(f"\nCONVERGED — both replicas hold the identical merged document,")
        say(f"with everyone's edits from both sides of the partition preserved,")
        say(f"and neither peer ever talked to the other while it was happening.")
        return 0
    else:
        say("\nFAILED TO CONVERGE — this should never happen.")
        return 1


def cmd_serve(args):
    from server import run_server
    run_server(port=args.port)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="braid", description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sim = sub.add_parser("simulate", help="run one seeded chaos simulation")
    p_sim.add_argument("--seed", type=int, default=1)
    p_sim.add_argument("--sites", type=int, default=4)
    p_sim.add_argument("--ops", type=int, default=60)
    p_sim.add_argument("--gossip-every", type=int, default=8)
    p_sim.add_argument("-v", "--verbose", action="store_true", help="print the full edit history")
    p_sim.set_defaults(func=cmd_simulate)

    p_sweep = sub.add_parser("sweep", help="run many seeds, report the convergence rate")
    p_sweep.add_argument("--count", type=int, default=100)
    p_sweep.add_argument("--sites", type=int, default=4)
    p_sweep.add_argument("--ops", type=int, default=40)
    p_sweep.add_argument("--gossip-every", type=int, default=8)
    p_sweep.set_defaults(func=cmd_sweep)

    p_scenario = sub.add_parser("scenario", help="narrated offline/reconnect walkthrough")
    p_scenario.set_defaults(func=cmd_scenario)

    p_serve = sub.add_parser("serve", help="start the live collaborative web editor")
    p_serve.add_argument("--port", type=int, default=8420)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
