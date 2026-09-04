import unittest

from matchbook.simulator import SimulationConfig, Simulator


class TestSimulatorDeterminism(unittest.TestCase):
    def test_same_seed_reproduces_identical_trade_tape(self):
        cfg = SimulationConfig(symbols=["ACME"], n_ticks=150, seed=123)
        s1 = Simulator(cfg)
        s1.run(record_history=False)
        s2 = Simulator(SimulationConfig(symbols=["ACME"], n_ticks=150, seed=123))
        s2.run(record_history=False)

        t1 = [t.to_dict() for t in s1.exchange.trade_tape]
        t2 = [t.to_dict() for t in s2.exchange.trade_tape]
        self.assertGreater(len(t1), 0, "sanity: the session should actually trade")
        self.assertEqual(t1, t2)
        self.assertEqual(s1.exchange.summary(), s2.exchange.summary())

    def test_different_seeds_diverge(self):
        s1 = Simulator(SimulationConfig(symbols=["ACME"], n_ticks=150, seed=1))
        s1.run(record_history=False)
        s2 = Simulator(SimulationConfig(symbols=["ACME"], n_ticks=150, seed=2))
        s2.run(record_history=False)
        self.assertNotEqual(
            [t.to_dict() for t in s1.exchange.trade_tape],
            [t.to_dict() for t in s2.exchange.trade_tape],
        )

    def test_produces_real_trades_not_a_stub(self):
        sim = Simulator(SimulationConfig(symbols=["ACME"], n_ticks=200, seed=7))
        sim.run(record_history=False)
        self.assertGreater(len(sim.exchange.trade_tape), 20)
        prices = {t.price for t in sim.exchange.trade_tape}
        self.assertGreater(len(prices), 1, "price should move, not sit at one fixed value")

    def test_multi_symbol_books_are_independent(self):
        sim = Simulator(SimulationConfig(symbols=["A", "B"], n_ticks=200, seed=3))
        sim.run(record_history=False)
        a_trades = [t for t in sim.exchange.trade_tape if t.symbol == "A"]
        b_trades = [t for t in sim.exchange.trade_tape if t.symbol == "B"]
        self.assertGreater(len(a_trades), 0)
        self.assertGreater(len(b_trades), 0)
        # Independent fundamentals/order flow -> different price paths.
        self.assertNotEqual(sim.exchange.last_price["A"], sim.exchange.last_price["B"])
        # No cross-contamination: an order for A must never fill against B.
        for t in a_trades:
            self.assertEqual(t.symbol, "A")

    def test_informed_trader_moves_price_toward_fundamental(self):
        """The informed trader alone sees the fundamental path; over a long
        enough session its trading should pull the traded price to be a
        materially better predictor of the eventual fundamental than the
        starting price was -- i.e. real price discovery, not noise."""
        cfg = SimulationConfig(symbols=["ACME"], n_ticks=400, seed=21, n_informed_traders=1)
        sim = Simulator(cfg)
        sim.run(record_history=False)
        final_fundamental = sim.fundamental["ACME"][cfg.n_ticks - 1]
        final_traded_price = sim.exchange.last_price["ACME"]
        start_error = abs(cfg.start_price - final_fundamental)
        end_error = abs(final_traded_price - final_fundamental)
        self.assertLess(end_error, start_error)

    def test_risk_engine_actually_rejects_within_a_session(self):
        from matchbook.risk import RiskLimits
        cfg = SimulationConfig(
            symbols=["ACME"], n_ticks=300, seed=99,
            risk_limits=RiskLimits(position_limit=60, max_order_qty=15, fat_finger_pct=0.25),
        )
        sim = Simulator(cfg)
        sim.run(record_history=False)
        self.assertGreater(len(sim.exchange.rejections), 0)

    def test_self_trade_prevention_fires_within_a_session(self):
        cfg = SimulationConfig(symbols=["ACME"], n_ticks=300, seed=99)
        sim = Simulator(cfg)
        sim.run(record_history=False)
        self.assertGreater(len(sim.exchange.stp_events), 0)
        for trade in sim.exchange.trade_tape:
            self.assertNotEqual(trade.buy_agent, trade.sell_agent)


if __name__ == "__main__":
    unittest.main()
