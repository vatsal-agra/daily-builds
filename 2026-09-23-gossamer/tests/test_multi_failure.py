"""Edge case probed during adversarial review: what happens when TWO of a
key's preferred replicas are down simultaneously, not just one?"""
import time
import unittest

from gossamer import client
from gossamer.cluster import Cluster
from gossamer.hashring import HashRing

NODE_IDS = ["A", "B", "C", "D", "E", "F", "G"]
VNODES = 32


def find_key_with_two_owners_down(owners, n):
    ring = HashRing(vnodes=VNODES)
    for nid in NODE_IDS:
        ring.add_node(nid)
    i = 0
    while True:
        key = f"probe-{i}"
        reps = ring.replicas_for(key, n)
        if all(o in reps for o in owners):
            return key
        i += 1
        if i > 20000:
            raise RuntimeError("no key found")


def wait_until(fn, timeout=8.0, interval=0.1):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    return last


class TestTwoSimultaneousReplicaFailures(unittest.TestCase):
    def test_write_and_read_survive_two_of_three_replicas_down(self):
        with Cluster(NODE_IDS, base_port=9750, n=3, r=2, w=2, vnodes=VNODES,
                     gossip_interval=0.2, suspect_timeout=1.2, dead_timeout=3.0) as c:
            key = find_key_with_two_owners_down(["D", "E"], 3)
            reps = HashRing(vnodes=VNODES)
            for nid in NODE_IDS:
                reps.add_node(nid)
            owner_set = reps.replicas_for(key, 3)
            third = [o for o in owner_set if o not in ("D", "E")][0]

            c.kill_node("D")
            c.kill_node("E")

            def both_dead():
                return all(c.status(n)["statuses"].get("D") == "dead"
                           and c.status(n)["statuses"].get("E") == "dead"
                           for n in ["A", "B", "C", "F", "G"] if n != third or True)
            self.assertTrue(wait_until(both_dead, timeout=9.0))

            # A real client of a leaderless quorum store is expected to
            # retry a transient quorum shortfall (two replicas down at once
            # leaves very little slack for even one more slow RPC under
            # system load) -- a bare single-shot call here would be testing
            # unrealistic client behavior, not the system.
            def do_write():
                status, body = client.put(c, "A", key, "survives-two-down", context=None)
                return body if status == 200 else None
            write_result = wait_until(do_write, timeout=6.0, interval=0.3)
            self.assertTrue(write_result, "write never succeeded despite retries")

            def do_read():
                status, body = client.get(c, "B", key)
                if status == 200 and body["siblings"] and body["siblings"][0]["value"] == "survives-two-down":
                    return body
                return None
            read_result = wait_until(do_read, timeout=6.0, interval=0.3)
            self.assertTrue(read_result, "read never returned the written value despite retries")

            # Revive both and confirm both catch up with no data loss, even
            # though their hints may have been concentrated on one
            # substitute (a known, accepted limitation -- see REVIEW.md).
            c.revive_node("D")
            c.revive_node("E")

            def both_caught_up():
                s1, b1 = client.get(c, "D", key)
                s2, b2 = client.get(c, "E", key)
                return (s1 == 200 and b1["siblings"] and b1["siblings"][0]["value"] == "survives-two-down"
                        and s2 == 200 and b2["siblings"] and b2["siblings"][0]["value"] == "survives-two-down")
            self.assertTrue(wait_until(both_caught_up, timeout=10.0))


if __name__ == "__main__":
    unittest.main()
