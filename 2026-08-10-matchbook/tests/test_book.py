import unittest
import _pathsetup  # noqa: F401

from order import Side, OrderType, reset_id_counter
from book import OrderBook, RejectedOrder


class TestOrderBook(unittest.TestCase):
    def setUp(self):
        reset_id_counter()
        self.book = OrderBook("T")

    def test_basic_cross_generates_trade(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 10, price=100, owner="a")
        _resting, trades = self.book.submit(Side.BUY, OrderType.LIMIT, 10, price=100, owner="b")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].price, 100)
        self.assertEqual(trades[0].qty, 10)
        self.assertIsNone(self.book.best_bid())
        self.assertIsNone(self.book.best_ask())

    def test_partial_fill_leaves_remainder_resting(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 4, price=100, owner="a")
        resting, trades = self.book.submit(Side.BUY, OrderType.LIMIT, 10, price=100, owner="b")
        self.assertEqual(trades[0].qty, 4)
        self.assertIsNotNone(resting)
        self.assertEqual(resting.qty, 6)
        self.assertEqual(self.book.best_bid(), 100)

    def test_price_time_priority_fifo_within_level(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="first")
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="second")
        _resting, trades = self.book.submit(Side.BUY, OrderType.LIMIT, 5, price=100, owner="taker")
        # the earlier-arrived resting order at the same price must fill first
        self.assertEqual(trades[0].maker_owner, "first")

    def test_price_priority_across_levels(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=105, owner="worse")
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="better")
        _resting, trades = self.book.submit(Side.BUY, OrderType.LIMIT, 5, price=110, owner="taker")
        self.assertEqual(trades[0].price, 100)
        self.assertEqual(trades[0].maker_owner, "better")

    def test_market_order_walks_multiple_levels(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 3, price=100, owner="a")
        self.book.submit(Side.SELL, OrderType.LIMIT, 3, price=101, owner="b")
        _resting, trades = self.book.submit(Side.BUY, OrderType.MARKET, 5, owner="taker")
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].price, 100)
        self.assertEqual(trades[0].qty, 3)
        self.assertEqual(trades[1].price, 101)
        self.assertEqual(trades[1].qty, 2)

    def test_market_order_no_liquidity_no_crash(self):
        resting, trades = self.book.submit(Side.BUY, OrderType.MARKET, 5, owner="taker")
        self.assertIsNone(resting)
        self.assertEqual(trades, [])

    def test_ioc_partial_fill_discards_remainder(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 3, price=100, owner="a")
        resting, trades = self.book.submit(Side.BUY, OrderType.IOC, 10, price=100, owner="taker")
        self.assertEqual(trades[0].qty, 3)
        self.assertIsNone(resting)  # remaining 7 must NOT rest on the book
        self.assertEqual(len(self.book.orders), 0)

    def test_fok_fails_when_insufficient_liquidity_and_book_unchanged(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="a")
        resting, trades = self.book.submit(Side.BUY, OrderType.FOK, 10, price=100, owner="taker")
        self.assertIsNone(resting)
        self.assertEqual(trades, [])
        self.assertEqual(self.book.best_ask(), 100)  # untouched

    def test_fok_succeeds_when_exactly_enough_liquidity(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="a")
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=101, owner="b")
        _resting, trades = self.book.submit(Side.BUY, OrderType.FOK, 10, price=101, owner="taker")
        self.assertEqual(sum(t.qty for t in trades), 10)

    def test_cancel_removes_order_and_is_idempotent_false_on_replay(self):
        resting, _ = self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="a")
        self.assertTrue(self.book.cancel(resting.id))
        self.assertFalse(self.book.cancel(resting.id))
        self.assertIsNone(self.book.best_ask())

    def test_cancel_unknown_id_returns_false(self):
        self.assertFalse(self.book.cancel(999999))

    def test_book_never_crosses_after_many_random_style_orders(self):
        # deterministic pseudo-random sequence of interleaved crossing orders
        prices = [95, 100, 105, 98, 102, 110, 90, 100, 100, 101]
        for i, p in enumerate(prices):
            side = Side.BUY if i % 2 == 0 else Side.SELL
            self.book.submit(side, OrderType.LIMIT, 3, price=p, owner=f"agent{i}")
            bb, ba = self.book.best_bid(), self.book.best_ask()
            if bb is not None and ba is not None:
                self.assertLess(bb, ba, f"book crossed after order {i}: bid={bb} ask={ba}")

    def test_self_trade_prevented_resting_cancelled_not_matched(self):
        resting, _ = self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="same")
        _r2, trades = self.book.submit(Side.BUY, OrderType.LIMIT, 5, price=100, owner="same")
        self.assertEqual(trades, [])  # no wash trade generated
        self.assertFalse(any(o.id == resting.id for o in self.book.orders.values()))

    def test_self_trade_prevention_lets_taker_match_through_to_next_order(self):
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="same")   # will be skipped
        self.book.submit(Side.SELL, OrderType.LIMIT, 5, price=100, owner="other")  # should fill instead
        _resting, trades = self.book.submit(Side.BUY, OrderType.LIMIT, 5, price=100, owner="same")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].maker_owner, "other")

    def test_rejects_non_positive_qty(self):
        with self.assertRaises(RejectedOrder):
            self.book.submit(Side.BUY, OrderType.LIMIT, 0, price=100, owner="a")
        with self.assertRaises(RejectedOrder):
            self.book.submit(Side.BUY, OrderType.LIMIT, -3, price=100, owner="a")

    def test_rejects_non_positive_price(self):
        with self.assertRaises(RejectedOrder):
            self.book.submit(Side.BUY, OrderType.LIMIT, 5, price=0, owner="a")
        with self.assertRaises(RejectedOrder):
            self.book.submit(Side.BUY, OrderType.LIMIT, 5, price=-10, owner="a")

    def test_limit_requires_price(self):
        with self.assertRaises(RejectedOrder):
            self.book.submit(Side.BUY, OrderType.LIMIT, 5, owner="a")

    def test_market_rejects_price(self):
        with self.assertRaises(RejectedOrder):
            self.book.submit(Side.BUY, OrderType.MARKET, 5, price=100, owner="a")

    def test_depth_best_first_ordering(self):
        self.book.submit(Side.BUY, OrderType.LIMIT, 1, price=98, owner="a")
        self.book.submit(Side.BUY, OrderType.LIMIT, 1, price=99, owner="b")
        self.book.submit(Side.SELL, OrderType.LIMIT, 1, price=102, owner="c")
        self.book.submit(Side.SELL, OrderType.LIMIT, 1, price=101, owner="d")
        d = self.book.depth(levels=5)
        self.assertEqual([p for p, _ in d["bids"]], [99, 98])
        self.assertEqual([p for p, _ in d["asks"]], [101, 102])


if __name__ == "__main__":
    unittest.main()
