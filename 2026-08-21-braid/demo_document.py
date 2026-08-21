#!/usr/bin/env python3
"""Demo: a shared outline document — the exact scenario PLAN.md promises
for the nested multi-type CRDT stretch feature. Three peers, offline and
unaware of each other, concurrently edit a title (LWW-register), a view
counter (PN-Counter), a tags collection (OR-Set), and a body of text
(RGA) — then gossip-merge over real SimNetwork chaos and converge to one
document, verified by direct equality, not eyeballing.
"""
import random
import sys

from crdt.document import Document
from network.sim_network import SimNetwork


def make_outline(peer_id):
    doc = Document(peer_id)
    doc.add_register("title")
    doc.add_counter("views")
    doc.add_set("tags")
    doc.add_text("body")
    return doc


def main():
    print("=== Braid document demo: a shared outline, 3 concurrent peers ===\n")

    alice = make_outline("alice")
    bob = make_outline("bob")
    carol = make_outline("carol")

    print("-- offline, concurrent edits (none of the three has seen the others yet) --")
    alice.field("title").set("Q3 Planning Doc")
    for ch in "Ship Braid.":
        alice.field("body").local_insert(len(alice.field("body")), ch)
    alice.field("tags").add("draft")
    alice.field("views").increment(3)
    print(f"alice: {alice.snapshot()}")

    bob.field("title").set("Q3 Planning (draft)")
    bob.field("tags").add("urgent")
    bob.field("views").increment(1)
    print(f"bob:   {bob.snapshot()}")

    carol.field("tags").add("reviewed")
    carol.field("tags").add("draft")
    carol.field("views").increment(5)
    for ch in " Also fix the demo.":
        carol.field("body").local_insert(len(carol.field("body")), ch)
    print(f"carol: {carol.snapshot()}")

    print("\n-- gossiping over a real chaotic SimNetwork (latency+reorder+dup, seed=42) --")
    peers = {"alice": alice, "bob": bob, "carol": carol}
    net = SimNetwork(list(peers), seed=42, latency_range=(1, 4), loss_p=0.0, dup_p=0.2)
    rng = random.Random(42)

    # each peer periodically gossips its full state to a random other peer
    for round_ in range(8):
        src = rng.choice(list(peers))
        dst = rng.choice([p for p in peers if p != src])
        net.send(src, dst, {"kind": "gossip", "type": "gossip", "state": peers[src].state()})

    def deliver(dst, msg):
        peers[dst].merge(msg["state"])

    net.run_until_quiescent(deliver)
    # one more full round to be sure everyone has converged (gossip only
    # reaches the direct target, so do a couple more rounds like real
    # anti-entropy would)
    for _ in range(3):
        for src in list(peers):
            for dst in list(peers):
                if src != dst:
                    net.send(src, dst, {"type": "gossip", "state": peers[src].state()})
        net.run_until_quiescent(deliver)

    print("\n-- after convergence --")
    snaps = {name: p.snapshot() for name, p in peers.items()}
    for name, snap in snaps.items():
        print(f"{name}: {snap}")

    first = next(iter(snaps.values()))
    all_match = all(s == first for s in snaps.values())
    print(f"\nAll three peers identical: {all_match}")
    if not all_match:
        print("FAILED: peers diverged")
        return 1

    expected_tags = {"draft", "urgent", "reviewed"}
    expected_views = 3 + 1 + 5
    ok = (
        first["tags"] == expected_tags
        and first["views"] == expected_views
        and "Ship Braid." in first["body"]
        and "Also fix the demo." in first["body"]
        and first["title"] in ("Q3 Planning Doc", "Q3 Planning (draft)")  # LWW picked one deterministically
    )
    print(f"Final title (LWW-resolved): {first['title']!r}")
    print(f"Final views (summed PN-Counter): {first['views']}")
    print(f"Final tags (union, add-wins OR-Set): {sorted(first['tags'])}")
    print(f"Final body (RGA text, both peers' sentences present): {first['body']!r}")
    print(f"\nDEMO {'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
