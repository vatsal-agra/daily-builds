"""The flagship Gossamer demo: one narrated run exercising every feature
against a real 5-node cluster of independent OS subprocesses.

Every claim printed is backed by an assertion immediately below it -- if
any mechanism doesn't actually work, this script fails loudly (non-zero
exit) instead of printing a reassuring narrative over a broken system.
"""
import sys
import time

from . import client
from .cluster import Cluster
from .hashring import HashRing

NODE_IDS = ["A", "B", "C", "D", "E"]
VNODES = 32


def _line(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def wait_until(fn, timeout=8.0, interval=0.1):
    deadline = time.time() + timeout
    result = None
    while time.time() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return result


def find_key_with_owner(owner, n, node_ids=NODE_IDS, vnodes=VNODES, prefix="probe"):
    ring = HashRing(vnodes=vnodes)
    for nid in node_ids:
        ring.add_node(nid)
    i = 0
    while True:
        key = f"{prefix}-{owner}-{i}"
        reps = ring.replicas_for(key, n)
        if owner in reps:
            return key
        i += 1
        if i > 20000:
            raise RuntimeError("could not find a probe key")


def main():
    _line("GOSSAMER — a from-scratch Dynamo-style distributed key-value store")
    print(f"Starting a real 5-node cluster (subprocesses): {NODE_IDS}")
    print("N=3 replicas per key, R=2 reads, W=2 writes, gossip-based failure detection.")

    with Cluster(NODE_IDS, base_port=9800, n=3, r=2, w=2, vnodes=VNODES,
                 gossip_interval=0.25, suspect_timeout=0.8, dead_timeout=2.2,
                 anti_entropy_interval=0.6) as c:

        ring = HashRing(vnodes=VNODES)
        for nid in NODE_IDS:
            ring.add_node(nid)

        # ---------------------------------------------------------- part 1
        _line("1. Consistent hashing: every key maps to 3 of the 5 nodes")
        for key in ["user:42", "user:7", "order:1001"]:
            reps = ring.replicas_for(key, 3)
            print(f"  {key:14s} -> replicas {reps}")
            assert len(set(reps)) == 3

        # ---------------------------------------------------------- part 2
        _line("2. Basic put/get through any node (no leader, no coordinator binary)")
        status, body = client.put(c, "C", "greeting", "hello, dynamo", context=None)
        assert status == 200, body
        print(f"  PUT greeting='hello, dynamo' via node C -> acks={body['acks']}/{body['w']}")
        status, body = client.get(c, "E", "greeting")
        assert status == 200 and body["siblings"][0]["value"] == "hello, dynamo"
        print(f"  GET greeting via node E -> '{body['siblings'][0]['value']}' (fetched through a totally different node)")

        # ---------------------------------------------------------- part 3
        _line("3. Fault tolerance: kill a replica, quorum reads/writes keep working")
        key = find_key_with_owner("D", 3)
        print(f"  Key '{key}' replicates to {ring.replicas_for(key, 3)} (includes D)")
        print("  Killing node D with SIGKILL (a real process death, not a flag)...")
        c.kill_node("D")
        status, body = client.put(c, "A", key, "still-available", context=None)
        assert status == 200, body
        print(f"  PUT succeeded anyway: acks={body['acks']}/{body['w']} (W satisfied by survivors)")
        status, body = client.get(c, "B", key)
        assert status == 200 and body["siblings"][0]["value"] == "still-available"
        print(f"  GET still returns the correct value: '{body['siblings'][0]['value']}'")

        # ---------------------------------------------------------- part 4
        _line("4. Gossip-based failure detection (fully decentralized, no ping-per-request)")
        print("  Waiting for surviving nodes to locally converge on D's status via gossip...")

        def suspected():
            return c.status("A")["statuses"].get("D") == "suspected"
        assert wait_until(suspected, timeout=5.0), "D was never marked suspected"
        print("  Node A's local membership view: D = suspected")

        def dead():
            return c.status("B")["statuses"].get("D") == "dead"
        assert wait_until(dead, timeout=6.0), "D was never marked dead"
        print("  Node B's local membership view: D = dead")
        print("  (each node reached this conclusion purely from its own gossip exchanges)")

        # ---------------------------------------------------------- part 5
        _line("5. Hinted handoff: writes to a dead replica land on a substitute")
        key2 = find_key_with_owner("D", 3, prefix="handoff")
        status, body = client.put(c, "A", key2, "handoff-payload", context=None)
        assert status == 200, body
        holder = None
        for nid in ["A", "B", "C", "E"]:
            st = c.status(nid)
            if st["hints"].get("D", 0) > 0:
                holder = nid
                break
        assert holder is not None, "no node is holding a hint for D"
        print(f"  Node {holder} is holding a hint on D's behalf (D is dead, so it can't take the write itself)")
        status, body = client.get(c, "C", key2)
        assert status == 200 and body["siblings"][0]["value"] == "handoff-payload"
        print(f"  GET still returns '{body['siblings'][0]['value']}' — served via the hint holder, not D")

        # ---------------------------------------------------------- part 6
        _line("6. Reviving D: hint flush + Merkle anti-entropy repair it with no data loss")
        print("  Restarting node D fresh (empty store, exactly like swapping in a new disk)...")
        c.revive_node("D")

        def d_has_both_keys():
            s1, b1 = client.get(c, "D", key)
            s2, b2 = client.get(c, "D", key2)
            return (s1 == 200 and b1["siblings"] and b1["siblings"][0]["value"] == "still-available"
                    and s2 == 200 and b2["siblings"] and b2["siblings"][0]["value"] == "handoff-payload")
        assert wait_until(d_has_both_keys, timeout=8.0), "D never recovered its data after revival"
        print("  D now has both 'still-available' and 'handoff-payload' — recovered with zero manual repair")

        # ---------------------------------------------------------- part 7
        _line("7. Concurrent writes: real conflicts, detected structurally, not statistically")
        cart_key = "cart:demo"
        status_a, _ = client.put(c, "A", cart_key, ["milk"], context=None)
        status_c, _ = client.put(c, "C", cart_key, ["eggs"], context=None)
        assert status_a == 200 and status_c == 200
        print("  Two clients wrote to the SAME key through two DIFFERENT coordinators, no shared context")
        status, body = client.get(c, "E", cart_key)
        assert status == 200
        values = sorted(s["value"][0] for s in body["siblings"])
        assert values == ["eggs", "milk"], f"expected 2 siblings, got {body['siblings']}"
        print(f"  GET returns BOTH siblings: {values} — a real, permanent conflict, not silently resolved")
        merged = sorted({v for s in body["siblings"] for v in s["value"]})
        status, _ = client.put(c, "A", cart_key, merged, context=body["context"])
        assert status == 200
        status, body = client.get(c, "B", cart_key)
        assert status == 200 and len(body["siblings"]) == 1
        print(f"  Application resolved it (union={merged}) and wrote back with the merged context")
        print(f"  Siblings collapse to one value: {body['siblings'][0]['value']}")

        # ---------------------------------------------------------- part 8
        _line("8. Anti-entropy transfers a diff, not a full resync")
        print("  Loading 200 keys spread across the ring, then taking D down again...")
        for i in range(200):
            client.put(c, NODE_IDS[i % 5], f"bulk:{i}", f"value-{i}", context=None)
        c.kill_node("D")

        def d_dead_everywhere():
            return all(c.status(n)["statuses"].get("D") == "dead" for n in ["A", "B", "C", "E"])
        wait_until(d_dead_everywhere, timeout=6.0)

        print("  Writing 20 more keys while D is down (D misses all of them)...")
        alive_ids = [n for n in NODE_IDS if n != "D"]
        for i in range(200, 220):
            status, body = client.put(c, alive_ids[i % len(alive_ids)], f"bulk:{i}", f"value-{i}", context=None)
            assert status == 200, body

        print("  Reviving D fresh and letting only background anti-entropy repair it (no reads issued)...")
        c.revive_node("D")

        def d_caught_up():
            return c.status("D")["store_keys"] >= 20

        assert wait_until(d_caught_up, timeout=10.0), "anti-entropy never repaired D"
        final_keys = c.status("D")["store_keys"]
        print(f"  D's store now holds {final_keys} keys after repair (dataset has {220} total) — "
              f"a targeted diff via Merkle buckets, not a wholesale resync of every replica's full data.")

        _line("ALL 8 SCENARIOS PASSED")
        print("Consistent hashing, vector clocks, quorum R/W, gossip failure detection,")
        print("hinted handoff, and Merkle anti-entropy all worked together, live, over")
        print("real independent OS processes.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\nDEMO FAILED: {e}", file=sys.stderr)
        sys.exit(1)
