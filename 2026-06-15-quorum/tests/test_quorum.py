"""Quorum verification suite — exercises every feature.

Run:  python3 -m unittest discover -s tests -v
  or: python3 tests/test_quorum.py
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quorum import Cluster, Config, Role
from quorum.network import Network, NetConfig
from quorum.raft import Node, LogEntry, Envelope, RequestVote, RequestVoteResp
from quorum.faults import run_chaos
from quorum.scenario import run_scenario, SCENARIOS
from quorum.linearizer import LinearizabilityChecker, HEvent, history_from_ops
from quorum.invariants import SafetyViolation
import quorum.raft as R


def kv_all_agree(cluster):
    stores = {tuple(sorted(cluster.kv_snapshot(i).items())) for i in cluster.alive}
    return len(stores) <= 1


# --------------------------------------------------------------------------- #
# 1. Core Raft: election + replication
# --------------------------------------------------------------------------- #
class TestCore(unittest.TestCase):
    def test_quiet_cluster_elects_single_leader(self):
        c = Cluster(n=5, seed=11)
        c.run(40)
        leaders = [i for i in c.alive if c.nodes[i].role == Role.LEADER]
        self.assertEqual(len(leaders), 1, "exactly one leader expected")

    def test_writes_replicate_to_all_nodes(self):
        c = Cluster(n=5, seed=12)
        c.run(25)
        for i in range(8):
            c.client_request(("put", f"k{i}", i)); c.run(6)
        self.assertTrue(c.run_until_quiescent())
        self.assertTrue(kv_all_agree(c))
        leader_kv = c.kv_snapshot(c.leader())
        self.assertEqual(len(leader_kv), 8)
        self.assertEqual(c.summary()["ops_committed"], 8)

    def test_get_returns_committed_value(self):
        c = Cluster(n=3, seed=13)
        c.run(25)
        c.client_request(("put", "x", 42)); c.run(15)
        op = c.client_request(("get", "x")); c.run(15)
        c.run_until_quiescent()
        self.assertTrue(op.committed)
        self.assertEqual(op.result, 42)

    def test_various_sizes_commit(self):
        for n in (1, 2, 3, 4, 5):
            c = Cluster(n=n, seed=20 + n)
            c.run(30)
            for i in range(4):
                c.client_request(("put", f"k{i}", i)); c.run(8)
            self.assertTrue(c.run_until_quiescent(max_ticks=400), f"n={n} not quiescent")
            self.assertEqual(c.summary()["ops_committed"], 4, f"n={n} commit fail")
            self.assertTrue(kv_all_agree(c), f"n={n} diverged")

    def test_single_node_regression(self):
        # F1/F2: a single node must self-elect and commit.
        c = Cluster(n=1, seed=1)
        c.run(15)
        self.assertEqual(c.nodes[0].role, Role.LEADER)
        for i in range(3):
            c.client_request(("put", f"k{i}", i)); c.run(5)
        c.run_until_quiescent(max_ticks=100)
        self.assertEqual(c.summary()["ops_committed"], 3)

    def test_invalid_cluster_size(self):
        with self.assertRaises(ValueError):
            Cluster(n=0)


# --------------------------------------------------------------------------- #
# 2. Safety properties (Figure 8, voting restriction)
# --------------------------------------------------------------------------- #
class TestSafetyRules(unittest.TestCase):
    def test_figure8_commit_rule(self):
        """A leader must NOT commit a prior-term entry on a bare majority, but
        may once a current-term entry reaches a majority (paper §5.4.2)."""
        def make():
            n = Node(0, [1, 2, 3, 4], random.Random(0), Config())
            n.role = Role.LEADER
            n.current_term = 4
            n.log = [LogEntry(0, ("noop",)), LogEntry(1, ("put", "a", 1)),
                     LogEntry(2, ("put", "b", 2))]
            n.commit_index = 1
            n.match_index = {1: 2, 2: 2, 3: 0, 4: 0}
            n.next_index = {p: n.last_log_index() + 1 for p in n.peers}
            return n
        n = make(); n._maybe_advance_commit()
        self.assertEqual(n.commit_index, 1, "must refuse to commit prior-term entry")
        n2 = make()
        n2.log.append(LogEntry(4, ("put", "c", 3)))
        n2.match_index = {1: 3, 2: 3, 3: 0, 4: 0}
        n2._maybe_advance_commit()
        self.assertEqual(n2.commit_index, 3, "current-term entry commits prior ones")

    def test_up_to_date_vote_restriction(self):
        """A node must reject a vote for a candidate with a less-up-to-date log."""
        n = Node(0, [1, 2], random.Random(0), Config())
        n.current_term = 5
        n.log = [LogEntry(0, ("noop",)), LogEntry(3, ("put", "a", 1)),
                 LogEntry(5, ("put", "b", 2))]
        # Candidate with an older last-log-term must be rejected.
        out = n.step(Envelope(1, 0, RequestVote(term=6, candidate_id=1,
                                                last_log_index=5, last_log_term=4)))
        self.assertFalse(out[0].body.vote_granted)
        # A candidate at least as up to date is granted.
        n2 = Node(0, [1, 2], random.Random(0), Config())
        n2.current_term = 5
        n2.log = [LogEntry(0, ("noop",)), LogEntry(3, ("put", "a", 1))]
        out2 = n2.step(Envelope(1, 0, RequestVote(term=6, candidate_id=1,
                                                  last_log_index=5, last_log_term=5)))
        self.assertTrue(out2[0].body.vote_granted)

    def test_election_safety_under_chaos(self):
        # The monitor enforces "<=1 leader per term"; a clean chaos run means it
        # never tripped.
        r = run_chaos(seed=7, ticks=1000)
        self.assertTrue(r.safety_ok, r.violation)


# --------------------------------------------------------------------------- #
# 3. Monitor has teeth (mutation tests)
# --------------------------------------------------------------------------- #
class TestMonitorTeeth(unittest.TestCase):
    def test_broken_vote_restriction_is_caught(self):
        orig = R.Node._handle_request_vote

        def broken(self, env):
            rv = env.body
            grant = rv.term >= self.current_term and self.voted_for in (None, rv.candidate_id)
            if grant:
                self.voted_for = rv.candidate_id
                self.election_elapsed = 0
            return [Envelope(self.id, env.src,
                             RequestVoteResp(term=self.current_term, vote_granted=grant))]
        R.Node._handle_request_vote = broken
        try:
            caught = sum(1 for s in range(15) if not run_chaos(seed=s, ticks=800).safety_ok)
        finally:
            R.Node._handle_request_vote = orig
        self.assertGreater(caught, 0, "monitor failed to catch a broken vote rule")


# --------------------------------------------------------------------------- #
# 4. Linearizability checker
# --------------------------------------------------------------------------- #
class TestLinearizer(unittest.TestCase):
    def test_rejects_stale_read(self):
        hist = [HEvent(0, ("put", "x", 1), "ok", 0, 2),
                HEvent(1, ("get", "x"), None, 3, 4)]  # reads None after put committed
        self.assertFalse(LinearizabilityChecker().check(hist))

    def test_accepts_valid_concurrent(self):
        hist = [HEvent(0, ("put", "x", 1), "ok", 0, 5),
                HEvent(1, ("get", "x"), None, 1, 2)]  # overlaps put, may see None
        self.assertTrue(LinearizabilityChecker().check(hist))

    def test_accepts_sequential_consistent(self):
        hist = [HEvent(0, ("put", "x", 1), "ok", 0, 1),
                HEvent(1, ("get", "x"), 1, 2, 3),
                HEvent(2, ("put", "x", 2), "ok", 4, 5),
                HEvent(3, ("get", "x"), 2, 6, 7)]
        self.assertTrue(LinearizabilityChecker().check(hist))

    def test_rejects_impossible_value(self):
        hist = [HEvent(0, ("put", "x", 1), "ok", 0, 1),
                HEvent(1, ("get", "x"), 99, 2, 3)]  # value never written
        self.assertFalse(LinearizabilityChecker().check(hist))

    def test_chaos_history_is_linearizable(self):
        for seed in range(10):
            r = run_chaos(seed=seed, ticks=800)
            self.assertTrue(r.linearizable, f"seed {seed} not linearizable")


# --------------------------------------------------------------------------- #
# 5. Network simulator
# --------------------------------------------------------------------------- #
class TestNetwork(unittest.TestCase):
    def test_determinism(self):
        a = run_chaos(seed=99, ticks=500)
        b = run_chaos(seed=99, ticks=500)
        self.assertEqual((a.ticks, a.ops_total, a.ops_committed),
                         (b.ticks, b.ops_total, b.ops_committed))

    def test_partition_isolates(self):
        net = Network(random.Random(0), NetConfig())
        net.set_partitions([{0, 1}, {2, 3, 4}])
        self.assertTrue(net.connected(0, 1))
        self.assertFalse(net.connected(1, 2))
        net.heal()
        self.assertTrue(net.connected(1, 2))

    def test_crash_blocks_link(self):
        net = Network(random.Random(0), NetConfig())
        net.crash(2)
        self.assertFalse(net.connected(2, 0))
        net.restart(2)
        self.assertTrue(net.connected(2, 0))

    def test_loss_drops_messages(self):
        net = Network(random.Random(1), NetConfig(loss_prob=1.0))
        env = Envelope(0, 1, "hi")
        net.send(env, 0)
        self.assertEqual(net.in_flight(), 0)  # everything dropped


# --------------------------------------------------------------------------- #
# 6. Fault injection + scenarios
# --------------------------------------------------------------------------- #
class TestFaultsAndScenarios(unittest.TestCase):
    def test_partition_then_heal_converges(self):
        c = Cluster(n=5, seed=4)
        c.run(25)
        for i in range(3):
            c.client_request(("put", f"a{i}", i)); c.run(6)
        old_leader = c.leader()
        others = [i for i in range(5) if i != old_leader]
        c.partition([{old_leader, others[0]}, set(others[1:])])
        c.run(80)
        c.client_request(("put", "post", 1)); c.run(20)
        c.heal()
        self.assertTrue(c.run_until_quiescent(max_ticks=400))
        self.assertTrue(kv_all_agree(c))

    def test_crash_restart_progress(self):
        c = Cluster(n=5, seed=6)
        c.run(25)
        c.client_request(("put", "a", 1)); c.run(10)
        leader = c.leader()
        c.crash(leader)
        c.run(60)
        c.client_request(("put", "b", 2)); c.run(20)
        c.restart(leader)
        self.assertTrue(c.run_until_quiescent(max_ticks=400))
        self.assertTrue(kv_all_agree(c))

    def test_all_scenarios_pass(self):
        for name in SCENARIOS:
            res = run_scenario(name)
            self.assertTrue(res["safety_ok"], f"{name}: {res['violation']}")
            self.assertTrue(res["linearizable"], f"{name}: not linearizable")
            self.assertTrue(res["settled"], f"{name}: did not settle")

    def test_chaos_sweep_clean(self):
        for seed in range(25):
            r = run_chaos(seed=seed, ticks=800)
            self.assertTrue(r.safety_ok and r.linearizable,
                            f"seed {seed}: {r.violation}")
            self.assertTrue(r.settled, f"seed {seed} did not settle")


# --------------------------------------------------------------------------- #
# 7. Log compaction / snapshots
# --------------------------------------------------------------------------- #
class TestSnapshots(unittest.TestCase):
    def test_install_snapshot_catch_up(self):
        c = Cluster(n=3, seed=2)
        c.run(20)
        leader = c.leader()
        laggard = [i for i in c.alive if i != leader][0]
        c.crash(laggard)
        for i in range(15):
            c.client_request(("put", f"k{i}", i)); c.run(6)
        for nid in c.alive:
            c.nodes[nid].take_snapshot()
        self.assertGreater(c.nodes[leader].base_index, 0, "leader should have compacted")
        c.restart(laggard)
        self.assertTrue(c.run_until_quiescent(max_ticks=400))
        self.assertEqual(c.kv_snapshot(laggard), c.kv_snapshot(c.leader()))
        self.assertGreater(c.nodes[laggard].base_index, 0,
                           "laggard should have installed a snapshot")

    def test_auto_snapshot_under_load(self):
        c = Cluster(n=3, seed=5, snapshot_threshold=10)
        c.run(20)
        for i in range(40):
            c.client_request(("put", f"k{i % 4}", i)); c.run(5)
        c.run_until_quiescent(max_ticks=400)
        self.assertGreater(max(c.nodes[i].base_index for i in c.alive), 0)
        self.assertTrue(kv_all_agree(c))


# --------------------------------------------------------------------------- #
# 8. CLI smoke
# --------------------------------------------------------------------------- #
class TestCLI(unittest.TestCase):
    def test_cli_commands_exit_zero(self):
        from quorum import cli
        self.assertEqual(cli.main(["run", "--seed", "1", "--writes", "3"]), 0)
        self.assertEqual(cli.main(["chaos", "--runs", "2", "--ticks", "500"]), 0)
        self.assertEqual(cli.main(["scenario", "split_brain"]), 0)
        self.assertEqual(cli.main(["demo"]), 0)

    def test_cli_bad_input(self):
        from quorum import cli
        self.assertEqual(cli.main(["chaos", "--nodes", "0"]), 2)
        self.assertEqual(cli.main(["scenario", "does_not_exist"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
