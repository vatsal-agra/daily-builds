import os
import random
import tempfile
import unittest

from matchbook.engine import Exchange
from matchbook.order import OrderStatus, OrderType, Side, TimeInForce
from matchbook.risk import RiskLimits


class TestExchangeBasics(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.journal_path = os.path.join(self.tmpdir, "ex.journal")

    def test_submit_assigns_incrementing_ids_and_seq(self):
        ex = Exchange(["X"], journal_path=self.journal_path)
        o1 = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 9.0, agent_id="a")
        o2 = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 9.0, agent_id="a")
        self.assertEqual(o2.order_id, o1.order_id + 1)
        self.assertEqual(o2.seq, o1.seq + 1)
        ex.close()

    def test_trade_updates_positions_and_cash_conservation(self):
        ex = Exchange(["X"], journal_path=self.journal_path)
        ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 10.0, agent_id="alice")
        ex.submit_order("X", Side.SELL, OrderType.LIMIT, 10, 10.0, agent_id="bob")
        self.assertEqual(ex.positions[("alice", "X")], 10)
        self.assertEqual(ex.positions[("bob", "X")], -10)
        # Zero-sum: total shares long + short across all agents is always 0.
        self.assertEqual(sum(ex.positions.values()), 0)
        # Zero-sum cash too (money that left alice's pocket entered bob's).
        self.assertAlmostEqual(ex.cash["alice"] + ex.cash["bob"], 0.0)
        ex.close()

    def test_cancel_and_modify_via_exchange(self):
        ex = Exchange(["X"], journal_path=self.journal_path)
        o = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 9.0, agent_id="a")
        self.assertTrue(ex.cancel_order(o.order_id))
        self.assertFalse(ex.cancel_order(o.order_id))  # already cancelled

        o2 = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 9.0, agent_id="a")
        replacement = ex.modify_order(o2.order_id, new_qty=25)
        self.assertEqual(replacement.remaining_qty, 25)
        ex.close()

    def test_unknown_symbol_order_raises_keyerror(self):
        ex = Exchange(["X"], journal_path=self.journal_path)
        with self.assertRaises(KeyError):
            ex.submit_order("NOPE", Side.BUY, OrderType.LIMIT, 10, 9.0, agent_id="a")
        ex.close()


class TestRiskIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.journal_path = os.path.join(self.tmpdir, "ex.journal")

    def test_position_limit_rejects_order(self):
        limits = RiskLimits(position_limit=50)
        ex = Exchange(["X"], journal_path=self.journal_path, risk_limits=limits)
        o = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 100, 9.0, agent_id="a")
        self.assertEqual(o.status, OrderStatus.REJECTED)
        self.assertEqual(len(ex.rejections), 1)
        self.assertNotIn(("a", "X"), ex.positions)
        ex.close()

    def test_max_order_qty_rejects(self):
        limits = RiskLimits(max_order_qty=10)
        ex = Exchange(["X"], journal_path=self.journal_path, risk_limits=limits)
        o = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 20, 9.0, agent_id="a")
        self.assertEqual(o.status, OrderStatus.REJECTED)
        ex.close()

    def test_fat_finger_collar_rejects_after_first_trade(self):
        limits = RiskLimits(fat_finger_pct=0.1, position_limit=None, max_order_qty=None)
        ex = Exchange(["X"], journal_path=self.journal_path, risk_limits=limits)
        ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 100.0, agent_id="a")
        ex.submit_order("X", Side.SELL, OrderType.LIMIT, 10, 100.0, agent_id="b")
        self.assertEqual(ex.last_price["X"], 100.0)
        wild = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 200.0, agent_id="c")
        self.assertEqual(wild.status, OrderStatus.REJECTED)
        ex.close()

    def test_no_fat_finger_check_before_any_trade(self):
        limits = RiskLimits(fat_finger_pct=0.01)
        ex = Exchange(["X"], journal_path=self.journal_path, risk_limits=limits)
        o = ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 5000.0, agent_id="a")
        self.assertEqual(o.status, OrderStatus.OPEN)  # nothing to collar against yet
        ex.close()


class TestCrashRecovery(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.journal_path = os.path.join(self.tmpdir, "ex.journal")

    def test_replay_reproduces_identical_fingerprint(self):
        ex = Exchange(["X", "Y"], journal_path=self.journal_path)
        rng = random.Random(5)
        agents = ["alice", "bob", "carol", "dave"]
        for i in range(200):
            symbol = rng.choice(["X", "Y"])
            side = rng.choice([Side.BUY, Side.SELL])
            qty = rng.randint(1, 20)
            price = round(rng.uniform(9, 11), 2)
            agent = rng.choice(agents)
            tif = rng.choice([TimeInForce.GTC, TimeInForce.IOC])
            ex.submit_order(symbol, side, OrderType.LIMIT, qty, price, tif, agent)
            if i % 17 == 0 and ex.all_orders:
                ex.cancel_order(rng.choice(list(ex.all_orders.keys())))
        live_fp = ex.state_fingerprint()
        live_summary = ex.summary()
        ex.close()

        replayed = Exchange.replay(self.journal_path, symbols=["X", "Y"])
        self.assertEqual(live_fp, replayed.state_fingerprint())
        self.assertEqual(live_summary, replayed.summary())

    def test_mid_session_crash_then_replay_matches_pre_crash_state(self):
        ex = Exchange(["X"], journal_path=self.journal_path)
        rng = random.Random(11)
        for i in range(150):
            side = rng.choice([Side.BUY, Side.SELL])
            ex.submit_order("X", side, OrderType.LIMIT, rng.randint(1, 10), round(rng.uniform(9, 11), 2), agent_id=f"a{i % 3}")
            if i == 74:
                # Snapshot fingerprint at the "moment of the crash," then
                # abandon `ex` without a clean shutdown.
                crash_fp = ex.state_fingerprint()
                break
        del ex  # no ex.close() -- simulating an abrupt crash

        recovered = Exchange.replay(self.journal_path, symbols=["X"])
        self.assertEqual(crash_fp, recovered.state_fingerprint())

    def test_rejected_orders_replay_identically(self):
        limits = RiskLimits(position_limit=20)
        ex = Exchange(["X"], journal_path=self.journal_path, risk_limits=limits)
        ex.submit_order("X", Side.BUY, OrderType.LIMIT, 100, 9.0, agent_id="a")  # rejected
        ex.submit_order("X", Side.BUY, OrderType.LIMIT, 5, 9.0, agent_id="a")    # accepted
        live_fp = ex.state_fingerprint()
        live_rejections = ex.rejections
        ex.close()

        # Note: replay takes no risk_limits (see REVIEW.md #4) -- the
        # journal already records the rejection verbatim.
        replayed = Exchange.replay(self.journal_path, symbols=["X"])
        self.assertEqual(live_fp, replayed.state_fingerprint())
        self.assertEqual(live_rejections, replayed.rejections)

    def test_replay_with_wrong_symbols_raises_clear_error(self):
        """Regression coverage for REVIEW.md finding #3: replaying with the
        wrong --symbols list must fail with a clear, actionable error, not
        a bare KeyError."""
        ex = Exchange(["X"], journal_path=self.journal_path)
        ex.submit_order("X", Side.BUY, OrderType.LIMIT, 10, 9.0, agent_id="a")
        ex.close()

        with self.assertRaises(ValueError) as ctx:
            Exchange.replay(self.journal_path, symbols=["WRONGSYM"])
        self.assertIn("X", str(ctx.exception))
        self.assertIn("--symbols", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
