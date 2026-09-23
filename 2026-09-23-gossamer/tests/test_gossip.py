import time
import unittest

from gossamer.gossip import Membership, ALIVE, SUSPECTED, DEAD


class TestMembership(unittest.TestCase):
    def test_self_always_alive(self):
        m = Membership("a", ["a", "b"], suspect_timeout=0.05, dead_timeout=0.1)
        self.assertEqual(m.status_of("a"), ALIVE)

    def test_starts_alive(self):
        m = Membership("a", ["a", "b"], suspect_timeout=0.05, dead_timeout=0.1)
        self.assertEqual(m.status_of("b"), ALIVE)

    def test_becomes_suspected_then_dead_without_updates(self):
        m = Membership("a", ["a", "b"], suspect_timeout=0.05, dead_timeout=0.15)
        time.sleep(0.08)
        self.assertEqual(m.status_of("b"), SUSPECTED)
        time.sleep(0.15)
        self.assertEqual(m.status_of("b"), DEAD)

    def test_merge_higher_heartbeat_revives_and_refreshes(self):
        m = Membership("a", ["a", "b"], suspect_timeout=0.05, dead_timeout=0.15)
        time.sleep(0.08)
        self.assertEqual(m.status_of("b"), SUSPECTED)
        revived = m.merge({"b": 5})
        self.assertEqual(revived, ["b"])
        self.assertEqual(m.status_of("b"), ALIVE)

    def test_merge_lower_or_equal_heartbeat_is_ignored(self):
        m = Membership("a", ["a", "b"], suspect_timeout=1.0, dead_timeout=2.0)
        m.merge({"b": 5})
        revived = m.merge({"b": 3})
        self.assertEqual(revived, [])
        self.assertEqual(m.snapshot_heartbeats()["b"], 5)

    def test_merge_does_not_report_revival_if_already_alive(self):
        m = Membership("a", ["a", "b"], suspect_timeout=5.0, dead_timeout=10.0)
        revived = m.merge({"b": 1})
        self.assertEqual(revived, [])  # was already alive, no transition

    def test_tick_self_advances_own_heartbeat(self):
        m = Membership("a", ["a", "b"])
        before = m.snapshot_heartbeats()["a"]
        m.tick_self()
        after = m.snapshot_heartbeats()["a"]
        self.assertEqual(after, before + 1)

    def test_merge_learns_about_unknown_node(self):
        m = Membership("a", ["a"])
        m.merge({"c": 2})
        self.assertIn("c", m.known_nodes())
        self.assertEqual(m.status_of("c"), ALIVE)

    def test_all_statuses_includes_every_known_node(self):
        m = Membership("a", ["a", "b", "c"])
        statuses = m.all_statuses()
        self.assertEqual(set(statuses.keys()), {"a", "b", "c"})


if __name__ == "__main__":
    unittest.main()
