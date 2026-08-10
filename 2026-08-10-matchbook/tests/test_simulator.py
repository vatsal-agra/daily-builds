import unittest
import _pathsetup  # noqa: F401

from simulator import MarketSimulator
from agents import Agent, Action, MarketMaker, NoiseTrader, MomentumTrader, MeanReversionTrader, StatArbTrader
from order import Side, OrderType


def build_session(seed, ticks=1200):
    sim = MarketSimulator(["ACME", "GLBX"], seed=seed)
    sim.seed_liquidity("ACME", mid=10000)
    sim.seed_liquidity("GLBX", mid=9800)
    sim.register(NoiseTrader("noise.acme.1", mid_guess=10000), "ACME")
    sim.register(NoiseTrader("noise.acme.2", mid_guess=10000, place_prob=0.4), "ACME")
    sim.register(NoiseTrader("noise.glbx.1", mid_guess=9800), "GLBX")
    sim.register(MarketMaker("mm.acme"), "ACME")
    sim.register(MarketMaker("mm.glbx"), "GLBX")
    sim.register(MomentumTrader("momentum.acme"), "ACME")
    sim.register(MeanReversionTrader("meanrev.acme"), "ACME")
    sim.register(StatArbTrader("statarb"), "ACME")
    sim.run(ticks)
    return sim


class TestSimulatorEndToEnd(unittest.TestCase):
    def test_runs_without_crossing_or_crashing(self):
        sim = build_session(seed=11)
        for sym, book in sim.books.items():
            bb, ba = book.best_bid(), book.best_ask()
            if bb is not None and ba is not None:
                self.assertLess(bb, ba, f"{sym} crossed: bid={bb} ask={ba}")

    def test_produces_real_trades_on_both_books(self):
        sim = build_session(seed=11)
        self.assertGreater(len(sim.trade_tape["ACME"]), 0)
        self.assertGreater(len(sim.trade_tape["GLBX"]), 0)

    def test_no_self_trades_anywhere(self):
        sim = build_session(seed=5)
        for sym, trades in sim.trade_tape.items():
            selftrades = [t for t in trades if t.maker_owner == t.taker_owner]
            self.assertEqual(selftrades, [], f"{sym} had self-trades: {selftrades}")

    def test_deterministic_same_seed_same_trade_tape(self):
        sim1 = build_session(seed=77, ticks=600)
        sim2 = build_session(seed=77, ticks=600)
        tape1 = [(t.ts, t.price, t.qty, t.maker_owner, t.taker_owner) for t in sim1.trade_tape["ACME"]]
        tape2 = [(t.ts, t.price, t.qty, t.maker_owner, t.taker_owner) for t in sim2.trade_tape["ACME"]]
        self.assertEqual(tape1, tape2)

    def test_different_seed_diverges(self):
        sim1 = build_session(seed=1, ticks=600)
        sim2 = build_session(seed=2, ticks=600)
        tape1 = [(t.ts, t.price) for t in sim1.trade_tape["ACME"]]
        tape2 = [(t.ts, t.price) for t in sim2.trade_tape["ACME"]]
        self.assertNotEqual(tape1, tape2)

    def test_leaderboard_covers_every_registered_agent(self):
        sim = build_session(seed=3)
        names = {row[0] for row in sim.leaderboard()}
        self.assertEqual(names, {a.name for a, _ in sim.agents})

    def test_t_zero_depth_snapshot_present_for_every_symbol(self):
        sim = build_session(seed=3, ticks=10)
        for sym in sim.symbols:
            snaps = sim.depth_recorders[sym].snapshots
            self.assertTrue(any(s["t"] == 0 for s in snaps), f"{sym} missing t=0 snapshot")


class _BrokenAgent(Agent):
    """Always emits an invalid action (qty=0) to verify the simulator
    survives a malformed custom strategy instead of crashing."""
    def on_tick(self, view, rng):
        return [Action("place", side=Side.BUY, otype=OrderType.LIMIT, qty=0, price=100)]


class TestSimulatorRobustness(unittest.TestCase):
    def test_malformed_agent_action_does_not_crash_session(self):
        sim = MarketSimulator(["X"], seed=1)
        sim.seed_liquidity("X", mid=10000)
        sim.register(_BrokenAgent("broken"), "X")
        sim.run(100)  # must not raise
        self.assertEqual(sim.rejected_actions, 100)

    def test_healthy_agents_unaffected_by_a_broken_peer(self):
        sim = MarketSimulator(["X"], seed=1)
        sim.seed_liquidity("X", mid=10000)
        sim.register(_BrokenAgent("broken"), "X")
        sim.register(NoiseTrader("noise", mid_guess=10000), "X")
        sim.run(300)
        self.assertGreater(len(sim.trade_tape["X"]), 0)


if __name__ == "__main__":
    unittest.main()
