import random
import unittest

from swarm.choking import DEFAULT_MAX_UNCHOKED, TitForTatChokePolicy, compute_unchoke_set


class TestComputeUnchokeSet(unittest.TestCase):
    def test_no_interested_peers_unchokes_nobody(self):
        unchoked, opt = compute_unchoke_set({}, set())
        self.assertEqual(unchoked, set())
        self.assertIsNone(opt)

    def test_fewer_interested_than_slots_unchokes_all(self):
        peers = {b"A" * 20, b"B" * 20}
        unchoked, _ = compute_unchoke_set({b"A" * 20: 10.0}, peers, max_unchoked=4, optimistic_slots=1)
        self.assertEqual(unchoked, peers)

    def test_ranks_by_download_rate_descending(self):
        rates = {b"A" * 20: 100.0, b"B" * 20: 50.0, b"C" * 20: 10.0, b"D" * 20: 1.0}
        peers = set(rates)
        unchoked, _ = compute_unchoke_set(rates, peers, max_unchoked=2, optimistic_slots=0)
        self.assertEqual(unchoked, {b"A" * 20, b"B" * 20})  # the two fastest, no optimistic slot to blur it

    def test_optimistic_slot_picks_from_non_regular_peers(self):
        rates = {b"A" * 20: 100.0, b"B" * 20: 50.0, b"C" * 20: 0.0}
        peers = set(rates)
        unchoked, optimistic = compute_unchoke_set(rates, peers, max_unchoked=2, optimistic_slots=1, rng=random.Random(1))
        self.assertIn(b"A" * 20, unchoked)  # the single regular slot goes to the fastest
        self.assertIsNotNone(optimistic)
        self.assertNotEqual(optimistic, b"A" * 20)  # optimistic is drawn from the *rest*, not double-counted
        self.assertEqual(len(unchoked), 2)

    def test_previous_optimistic_kept_if_still_eligible(self):
        rates = {b"A" * 20: 100.0, b"B" * 20: 0.0, b"C" * 20: 0.0}
        peers = set(rates)
        unchoked, optimistic = compute_unchoke_set(
            rates, peers, max_unchoked=2, optimistic_slots=1, previous_optimistic=b"C" * 20
        )
        self.assertEqual(optimistic, b"C" * 20)  # sticky, not re-rolled every tick

    def test_previous_optimistic_dropped_if_no_longer_eligible(self):
        # A's rate jumped enough to win a regular slot on its own merit, so
        # it can no longer occupy the optimistic slot too (that would waste
        # a slot double-counting one peer) -- B gets picked instead.
        rates = {b"A" * 20: 100.0, b"B" * 20: 1.0}
        peers = set(rates)
        unchoked, optimistic = compute_unchoke_set(
            rates, peers, max_unchoked=2, optimistic_slots=1, previous_optimistic=b"A" * 20
        )
        self.assertEqual(optimistic, b"B" * 20)
        self.assertEqual(unchoked, peers)

    def test_ties_broken_deterministically(self):
        rates = {b"A" * 20: 5.0, b"B" * 20: 5.0}
        peers = set(rates)
        u1, _ = compute_unchoke_set(rates, peers, max_unchoked=1, optimistic_slots=0)
        u2, _ = compute_unchoke_set(rates, peers, max_unchoked=1, optimistic_slots=0)
        self.assertEqual(u1, u2)  # same input -> same output, not coin-flip-random

    def test_missing_rate_treated_as_zero_not_excluded(self):
        peers = {b"A" * 20, b"B" * 20}
        unchoked, _ = compute_unchoke_set({b"A" * 20: 5.0}, peers, max_unchoked=1, optimistic_slots=0)
        self.assertEqual(unchoked, {b"A" * 20})  # B (rate 0, no entry at all) correctly loses


class _FakeConn:
    def __init__(self, peer_interested):
        self.peer_interested = peer_interested


class _FakePieceManager:
    def __init__(self, bytes_downloaded_from):
        self.bytes_downloaded_from = bytes_downloaded_from


class TestTitForTatChokePolicy(unittest.TestCase):
    def test_first_tick_has_no_rate_history_but_still_unchokes_interested(self):
        policy = TitForTatChokePolicy(max_unchoked=4, optimistic_slots=1, seed=0)
        conns = {b"A" * 20: _FakeConn(True)}
        pm = _FakePieceManager({})
        unchoked = policy(conns, pm)
        self.assertEqual(unchoked, {b"A" * 20})

    def test_rewards_peer_with_higher_measured_rate_over_ticks(self):
        import time

        policy = TitForTatChokePolicy(max_unchoked=1, optimistic_slots=0, seed=0)
        conns = {b"A" * 20: _FakeConn(True), b"B" * 20: _FakeConn(True)}
        pm = _FakePieceManager({})
        policy(conns, pm)  # establish baseline (t0)
        time.sleep(0.05)
        pm.bytes_downloaded_from = {b"A" * 20: 100_000, b"B" * 20: 10}
        unchoked = policy(conns, pm)
        self.assertEqual(unchoked, {b"A" * 20})

    def test_rotate_every_forces_a_reroll(self):
        policy = TitForTatChokePolicy(max_unchoked=1, optimistic_slots=1, rotate_every=1, seed=0)
        conns = {b"A" * 20: _FakeConn(True), b"B" * 20: _FakeConn(True), b"C" * 20: _FakeConn(True)}
        pm = _FakePieceManager({})
        seen_optimistic = set()
        for _ in range(20):
            policy(conns, pm)
            if policy._optimistic:
                seen_optimistic.add(policy._optimistic)
        self.assertGreater(len(seen_optimistic), 1)  # rotate_every=1 should visit more than one peer over 20 ticks


if __name__ == "__main__":
    unittest.main()
