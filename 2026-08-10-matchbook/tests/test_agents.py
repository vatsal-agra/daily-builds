import random
import unittest
import _pathsetup  # noqa: F401

from order import Side, OrderType, Trade
from agents import BookView, MarketMaker, MomentumTrader, MeanReversionTrader, NoiseTrader, StatArbTrader


def make_view(symbol="X", best_bid=None, best_ask=None, recent_trades=None,
              my_open_orders=None, my_inventory=0, my_cash=0, other=None):
    return BookView(
        symbol=symbol, tick=0, best_bid=best_bid, best_ask=best_ask,
        depth={"bids": [], "asks": []},
        recent_trades=recent_trades or [],
        my_open_orders=my_open_orders or [],
        my_inventory=my_inventory, my_cash=my_cash,
        other_symbol_view=other,
    )


class TestMarketMaker(unittest.TestCase):
    def test_quotes_never_cross_when_book_thin(self):
        mm = MarketMaker("mm")
        view = make_view(best_bid=100, best_ask=101)
        actions = mm.on_tick(view, random.Random(1))
        places = [a for a in actions if a.kind == "place"]
        bid = next(a.price for a in places if a.side is Side.BUY)
        ask = next(a.price for a in places if a.side is Side.SELL)
        self.assertLess(bid, ask)

    def test_sits_out_with_no_price_discovery_yet(self):
        mm = MarketMaker("mm")
        view = make_view()
        actions = mm.on_tick(view, random.Random(1))
        self.assertEqual([a for a in actions if a.kind == "place"], [])

    def test_skews_quotes_away_from_inventory(self):
        mm = MarketMaker("mm", inventory_skew=10)
        rng = random.Random(1)
        neutral = mm.on_tick(make_view(best_bid=100, best_ask=101, my_inventory=0), rng)
        long_book = mm.on_tick(make_view(best_bid=100, best_ask=101, my_inventory=300), rng)
        neutral_bid = next(a.price for a in neutral if a.kind == "place" and a.side is Side.BUY)
        long_bid = next(a.price for a in long_book if a.kind == "place" and a.side is Side.BUY)
        self.assertLess(long_bid, neutral_bid)  # already long -> quote a less eager bid

    def test_stops_quoting_a_side_past_max_inventory(self):
        mm = MarketMaker("mm", max_inventory=50)
        view = make_view(best_bid=100, best_ask=101, my_inventory=50)
        actions = mm.on_tick(view, random.Random(1))
        sides = {a.side for a in actions if a.kind == "place"}
        self.assertNotIn(Side.BUY, sides)  # already at the long cap


class TestMomentumAndMeanReversion(unittest.TestCase):
    def _trades(self, prices):
        return [Trade(price=p, qty=1, ts=i, aggressor_side=Side.BUY,
                       maker_order_id=i, taker_order_id=i, maker_owner="x", taker_owner="y")
                for i, p in enumerate(prices)]

    def test_momentum_buys_on_uptrend(self):
        mom = MomentumTrader(short_n=3, long_n=6, threshold=1, name="m")
        prices = [100, 100, 100, 100, 100, 100, 130, 131, 132]
        actions = mom.on_tick(make_view(recent_trades=self._trades(prices)), random.Random(1))
        self.assertTrue(actions)
        self.assertEqual(actions[0].side, Side.BUY)

    def test_momentum_silent_without_enough_history(self):
        mom = MomentumTrader(short_n=3, long_n=20, name="m")
        actions = mom.on_tick(make_view(recent_trades=self._trades([100, 101])), random.Random(1))
        self.assertEqual(actions, [])

    def test_mean_reversion_sells_when_price_spikes_above_average(self):
        mr = MeanReversionTrader(window=5, threshold=2, name="mr")
        prices = [100, 100, 100, 100, 130]
        actions = mr.on_tick(make_view(recent_trades=self._trades(prices)), random.Random(1))
        self.assertTrue(actions)
        self.assertEqual(actions[0].side, Side.SELL)  # bet on reversion down


class TestNoiseTrader(unittest.TestCase):
    def test_never_crashes_on_empty_book(self):
        nt = NoiseTrader("n", mid_guess=1000)
        actions = nt.on_tick(make_view(), random.Random(1))
        for a in actions:
            if a.kind == "place":
                self.assertGreaterEqual(a.price, 1)

    def test_drift_anchor_stays_positive_over_many_ticks(self):
        nt = NoiseTrader("n", mid_guess=2, drift_step=5)
        rng = random.Random(2)
        for _ in range(500):
            nt.on_tick(make_view(), rng)
        self.assertGreaterEqual(nt.mid_guess, 1)


class TestStatArb(unittest.TestCase):
    def test_trades_both_legs_in_opposite_directions(self):
        # spread_hist accumulates one sample per on_tick call (the
        # current A-vs-B spread), not one per historical trade in the
        # view — so building up `window` samples means calling on_tick
        # `window` times, with the spread staying flat until the final
        # tick diverges.
        sa = StatArbTrader("sa", window=3, threshold=5)
        rng = random.Random(1)
        flat = make_view(symbol="A", recent_trades=self.__class__._trades([100]),
                          other=make_view(symbol="B", recent_trades=self.__class__._trades([100])))
        for _ in range(2):
            self.assertEqual(sa.on_tick(flat, rng), [])  # not enough history yet, and no divergence anyway

        diverged = make_view(symbol="A", recent_trades=self.__class__._trades([140]),
                              other=make_view(symbol="B", recent_trades=self.__class__._trades([100])))
        actions = sa.on_tick(diverged, rng)
        self.assertEqual(len(actions), 2)
        by_symbol = {a.symbol: a.side for a in actions}
        self.assertNotEqual(by_symbol["A"], by_symbol["B"])

    @staticmethod
    def _trades(prices):
        return [Trade(price=p, qty=1, ts=i, aggressor_side=Side.BUY,
                       maker_order_id=i, taker_order_id=i, maker_owner="x", taker_owner="y")
                for i, p in enumerate(prices)]


if __name__ == "__main__":
    unittest.main()
