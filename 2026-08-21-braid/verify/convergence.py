"""Property-based Strong Eventual Consistency (SEC) verification.

SEC, precisely: if two peers have delivered the same *set* of updates
(regardless of order, count, or timing), they are in equivalent state.
This module proves it by construction, not by inspection — for many
random seeds, it wires up N `RGA` peers behind `CausalDeliveryBuffer`s,
drives them through a `SimNetwork` with real reordering/duplication/
partition+heal, runs the network to quiescence, and asserts every peer's
`.text()` is byte-identical. A failure here means the CRDT algebra is
broken — this is the same role Quorum's (2026-06-15) safety-invariant
monitor plays for a consensus-based system, adapted to a leaderless one.

It also runs a second, deliberately honest pair of scenarios: a
lossy network *without* anti-entropy (which — correctly — does NOT
always converge, a real property of pure op-broadcast CRDT systems, not
a bug) and the same scenario *with* periodic anti-entropy resync, which
restores convergence. Both outcomes are asserted, not just described.
"""

from __future__ import annotations

import random

from crdt.clock import CausalDeliveryBuffer
from crdt.rga import RGA
from network.sim_network import SimNetwork

ALPHABET = "abcdefXYZ   .,\n"


def _make_peers(peer_ids):
    peers = {p: RGA(p) for p in peer_ids}
    buffers = {p: CausalDeliveryBuffer(peers[p].has_id) for p in peer_ids}
    return peers, buffers


def _deliver_fn(peers, buffers):
    def deliver(dst, op):
        buffers[dst].submit(op, peers[dst].apply_remote)

    return deliver


def _random_local_edit(peer: RGA, rng: random.Random):
    n = len(peer)
    if n == 0 or rng.random() < 0.7:
        idx = rng.randint(0, n)
        return peer.local_insert(idx, rng.choice(ALPHABET))
    idx = rng.randint(0, n - 1)
    return peer.local_delete(idx)


def _drain_pending(peers, buffers):
    """After all messages are delivered, any op still waiting in a buffer
    on an unmet dependency is a genuine bug (deps should be satisfiable
    once everything's been delivered) — surfaced as an assertion, not
    silently ignored."""
    stuck = {p: len(buf) for p, buf in buffers.items() if len(buf) > 0}
    return stuck


# ----------------------------------------------------------------------
# Tier 1: reliable-eventually delivery (reorder + duplicate + partition/heal,
# zero permanent loss) — the hard correctness gate. Must ALWAYS converge.
# ----------------------------------------------------------------------


def run_sec_scenario(seed: int, n_peers: int = 4, rounds: int = 6, edits_per_round: int = 6) -> dict:
    rng = random.Random(seed)
    peer_ids = [f"P{i}" for i in range(n_peers)]
    peers, buffers = _make_peers(peer_ids)
    net = SimNetwork(
        peer_ids, seed=seed, latency_range=(1, 5), loss_p=0.0, dup_p=0.25
    )
    deliver = _deliver_fn(peers, buffers)

    partition_round = rounds // 2
    for r in range(rounds):
        if r == partition_round and n_peers >= 3:
            half = n_peers // 2
            net.partition(peer_ids[:half], peer_ids[half:], ticks=8)
        for _ in range(edits_per_round):
            p = rng.choice(peer_ids)
            op = _random_local_edit(peers[p], rng)
            net.broadcast(p, op)
        # let some ticks pass mid-round so ops interleave with more sends
        for _ in range(rng.randint(1, 3)):
            net.step(deliver)

    net.run_until_quiescent(deliver, max_ticks=200_000)

    texts = {p: peers[p].text() for p in peer_ids}
    stuck = _drain_pending(peers, buffers)
    converged = len(set(texts.values())) == 1 and not stuck
    return {
        "seed": seed,
        "converged": converged,
        "texts": texts,
        "stuck": stuck,
        "final_length": len(next(iter(texts.values()))),
    }


# ----------------------------------------------------------------------
# Tier 2: permanent loss, no anti-entropy — expected to sometimes diverge.
# Tier 3: same, but with periodic anti-entropy resync — expected to converge.
# ----------------------------------------------------------------------


def _anti_entropy_round(peers, buffers, peer_ids, rng):
    """Full pairwise op-log resync over an assumed-reliable side channel
    (modeling e.g. a direct reconnect handshake, not the lossy broadcast
    channel) — real production CRDT systems (Automerge, Redis CRDB) use
    exactly this hybrid: best-effort op broadcast day-to-day, periodic
    state reconciliation to guarantee convergence despite loss."""
    order = list(peer_ids)
    rng.shuffle(order)
    for i, a in enumerate(order):
        b = order[(i + 1) % len(order)]
        missing_in_b = peers[a].known_op_keys() - peers[b].known_op_keys()
        for op in peers[a].op_log:
            # must match RGA._log's own key scheme exactly (op_id for
            # delete/undelete, id for insert) or this silently never
            # finds anything to resend for whichever type it gets wrong
            key = (op["type"], op["op_id"]) if "op_id" in op else (op["type"], op["id"])
            if key in missing_in_b:
                buffers[b].submit(op, peers[b].apply_remote)


def run_lossy_scenario(seed: int, n_peers: int = 4, rounds: int = 6, edits_per_round: int = 5,
                        loss_p: float = 0.3, use_anti_entropy: bool = False) -> dict:
    rng = random.Random(seed)
    peer_ids = [f"P{i}" for i in range(n_peers)]
    peers, buffers = _make_peers(peer_ids)
    net = SimNetwork(peer_ids, seed=seed, latency_range=(1, 3), loss_p=loss_p, dup_p=0.1)
    deliver = _deliver_fn(peers, buffers)

    for r in range(rounds):
        for _ in range(edits_per_round):
            p = rng.choice(peer_ids)
            op = _random_local_edit(peers[p], rng)
            net.broadcast(p, op)
        for _ in range(3):
            net.step(deliver)
        if use_anti_entropy:
            _anti_entropy_round(peers, buffers, peer_ids, rng)

    # let anything still in flight finish (no partitions active, so this
    # always quiesces even with loss_p > 0 — lost messages simply vanish
    # rather than staying "in flight")
    for _ in range(20):
        net.step(deliver)
    if use_anti_entropy:
        # final settle round so post-loop resends land before comparing
        _anti_entropy_round(peers, buffers, peer_ids, rng)
        _anti_entropy_round(peers, buffers, peer_ids, rng)

    texts = {p: peers[p].text() for p in peer_ids}
    converged = len(set(texts.values())) == 1
    return {"seed": seed, "converged": converged, "texts": texts}


# ----------------------------------------------------------------------
# report / CLI
# ----------------------------------------------------------------------


def run_report(n_trials: int = 150, verbose: bool = False) -> bool:
    print(f"=== Tier 1: SEC under reorder + duplication + partition/heal (0 loss), {n_trials} trials ===")
    failures = []
    for seed in range(n_trials):
        result = run_sec_scenario(seed)
        if not result["converged"]:
            failures.append(result)
            if verbose or len(failures) <= 3:
                print(f"  seed {seed}: DIVERGED")
                for p, t in result["texts"].items():
                    print(f"    {p}: {t!r}")
                if result["stuck"]:
                    print(f"    stuck in buffers: {result['stuck']}")
    tier1_ok = not failures
    print(f"  -> {n_trials - len(failures)}/{n_trials} converged" + (" — ALL PASS" if tier1_ok else f" — {len(failures)} FAILURES"))

    print("\n=== Tier 2: lossy network (loss_p=0.3), NO anti-entropy — expected to sometimes diverge ===")
    lossy_no_ae = [run_lossy_scenario(seed, use_anti_entropy=False) for seed in range(40)]
    diverged = sum(1 for r in lossy_no_ae if not r["converged"])
    print(f"  -> {diverged}/40 scenarios diverged under pure loss with no repair mechanism")
    print("     (this is EXPECTED and correct: op-broadcast alone cannot survive permanent loss;")
    print("      it demonstrates why anti-entropy exists, rather than hiding the limitation.)")

    print("\n=== Tier 3: same lossy network, WITH periodic anti-entropy resync ===")
    lossy_with_ae = [run_lossy_scenario(seed, use_anti_entropy=True) for seed in range(40)]
    ae_diverged = sum(1 for r in lossy_with_ae if not r["converged"])
    tier3_ok = ae_diverged == 0
    print(f"  -> {40 - ae_diverged}/40 converged" + (" — ALL PASS (anti-entropy restores SEC)" if tier3_ok else f" — {ae_diverged} STILL DIVERGED"))

    overall = tier1_ok and diverged > 0 and tier3_ok
    print(f"\n=== Overall: {'PASS' if overall else 'FAIL'} ===")
    if not (diverged > 0):
        print("  NOTE: tier 2 was expected to show >=1 divergence to prove the demonstration is real;")
        print("        0 divergences would mean the lossy scenario wasn't actually adversarial enough.")
    return overall


if __name__ == "__main__":
    import sys

    ok = run_report(n_trials=150)
    sys.exit(0 if ok else 1)
