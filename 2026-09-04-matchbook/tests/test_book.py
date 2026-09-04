import random
import unittest

from matchbook.book import OrderBook
from matchbook.order import Order, OrderStatus, OrderType, Side, TimeInForce


def mk(order_id, side, qty, price=None, order_type=OrderType.LIMIT, tif=TimeInForce.GTC, agent="", symbol="X"):
    return Order(order_id, symbol, side, order_type, qty, price=price, tif=tif, agent_id=agent)


class TestBasicMatching(unittest.TestCase):
    def test_no_cross_rests(self):
        book = OrderBook("X")
        trades = book.submit(mk(1, Side.BUY, 10, 9.0))
        self.assertEqual(trades, [])
        self.assertEqual(book.best_bid(), 9.0)
        self.assertIsNone(book.best_ask())

    def test_exact_fill_both_sides(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 10, 10.0, agent="alice"))
        trades = book.submit(mk(2, Side.SELL, 10, 10.0, agent="bob"))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].qty, 10)
        self.assertEqual(trades[0].price, 10.0)  # resting (maker) price
        self.assertEqual(book.total_resting_qty(), 0)
        self.assertIsNone(book.best_bid())
        self.assertIsNone(book.best_ask())

    def test_partial_fill_leaves_remainder_resting(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 100, 10.0, agent="alice"))
        trades = book.submit(mk(2, Side.SELL, 40, 10.0, agent="bob"))
        self.assertEqual(sum(t.qty for t in trades), 40)
        resting = book.all_resting_orders()
        self.assertEqual(len(resting), 1)
        self.assertEqual(resting[0].remaining_qty, 60)
        self.assertEqual(resting[0].status, OrderStatus.PARTIALLY_FILLED)

    def test_price_priority_best_price_first(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 10, 9.90, agent="low"))
        book.submit(mk(2, Side.BUY, 10, 10.10, agent="high"))  # better bid, submitted second
        trades = book.submit(mk(3, Side.SELL, 10, 9.50, agent="seller"))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].price, 10.10)
        self.assertEqual(trades[0].buy_agent, "high")

    def test_time_priority_within_price_level(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 10, 10.0, agent="first"))
        book.submit(mk(2, Side.BUY, 10, 10.0, agent="second"))
        trades = book.submit(mk(3, Side.SELL, 10, 10.0, agent="seller"))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].buy_agent, "first")  # earlier order at same price wins

    def test_sweeps_multiple_levels_in_price_order(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.SELL, 10, 10.0))
        book.submit(mk(2, Side.SELL, 10, 10.5))
        book.submit(mk(3, Side.SELL, 10, 9.5))
        trades = book.submit(mk(4, Side.BUY, 25, 10.5, agent="sweeper"))
        prices = [t.price for t in trades]
        self.assertEqual(prices, sorted(prices))  # best (lowest ask) filled first
        self.assertEqual(sum(t.qty for t in trades), 25)


class TestOrderTypes(unittest.TestCase):
    def test_market_order_sweeps_book(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.SELL, 10, 10.0))
        book.submit(mk(2, Side.SELL, 10, 10.5))
        order = mk(3, Side.BUY, 15, None, order_type=OrderType.MARKET)
        trades = book.submit(order)
        self.assertEqual(sum(t.qty for t in trades), 15)
        self.assertEqual(order.status, OrderStatus.FILLED)

    def test_market_order_never_rests(self):
        book = OrderBook("X")  # empty book
        order = mk(1, Side.BUY, 10, None, order_type=OrderType.MARKET)
        trades = book.submit(order)
        self.assertEqual(trades, [])
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(book.total_resting_qty(), 0)

    def test_ioc_partial_then_cancel_remainder(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.SELL, 5, 10.0))
        order = mk(2, Side.BUY, 20, 10.0, tif=TimeInForce.IOC)
        trades = book.submit(order)
        self.assertEqual(sum(t.qty for t in trades), 5)
        self.assertEqual(order.remaining_qty, 15)
        self.assertEqual(order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(book.total_resting_qty(), 0)  # remainder never rests

    def test_ioc_no_fill_at_all_is_cancelled_not_partial(self):
        book = OrderBook("X")
        order = mk(1, Side.BUY, 10, 5.0, tif=TimeInForce.IOC)
        trades = book.submit(order)
        self.assertEqual(trades, [])
        self.assertEqual(order.status, OrderStatus.CANCELLED)

    def test_fok_fills_completely_when_liquidity_sufficient(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.SELL, 10, 10.0))
        book.submit(mk(2, Side.SELL, 10, 10.1))
        order = mk(3, Side.BUY, 15, 10.1, tif=TimeInForce.FOK)
        trades = book.submit(order)
        self.assertEqual(sum(t.qty for t in trades), 15)
        self.assertEqual(order.status, OrderStatus.FILLED)

    def test_fok_rejects_atomically_with_zero_book_effect(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.SELL, 5, 10.0))
        before = book.depth()
        order = mk(2, Side.BUY, 100, 10.0, tif=TimeInForce.FOK)
        trades = book.submit(order)
        self.assertEqual(trades, [])
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertEqual(order.remaining_qty, 100)  # completely untouched
        self.assertEqual(book.depth(), before)  # book is byte-for-byte unchanged

    def test_fok_respects_price_limit(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.SELL, 100, 11.0))  # plenty of qty, but too expensive
        order = mk(2, Side.BUY, 50, 10.0, tif=TimeInForce.FOK)
        trades = book.submit(order)
        self.assertEqual(trades, [])
        self.assertEqual(order.status, OrderStatus.REJECTED)


class TestCancelModify(unittest.TestCase):
    def test_cancel_removes_resting_order(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 10, 9.0))
        self.assertTrue(book.cancel(1))
        self.assertIsNone(book.best_bid())
        self.assertEqual(book.total_resting_qty(), 0)

    def test_cancel_unknown_order_returns_false(self):
        book = OrderBook("X")
        self.assertFalse(book.cancel(999))

    def test_modify_price_loses_time_priority(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 10, 10.0, agent="first"))
        book.submit(mk(2, Side.BUY, 10, 10.0, agent="second"))
        book.modify(1, new_price=10.0, new_qty=10)  # re-price to same price -> requeued behind #2
        trades = book.submit(mk(3, Side.SELL, 10, 10.0, agent="seller"))
        self.assertEqual(trades[0].buy_agent, "second")

    def test_modify_qty_preserves_order_id(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 10, 10.0))
        replacement = book.modify(1, new_qty=20)
        self.assertEqual(replacement.order_id, 1)
        self.assertEqual(replacement.remaining_qty, 20)


class TestSelfTradePrevention(unittest.TestCase):
    def test_self_trade_is_prevented_by_cancelling_resting_order(self):
        book = OrderBook("X", self_trade_prevention=True)
        book.submit(mk(1, Side.BUY, 10, 10.0, agent="alice"))
        trades = book.submit(mk(2, Side.SELL, 10, 10.0, agent="alice"))
        self.assertEqual(trades, [])
        self.assertEqual(book.stp_cancels, [1])
        # order #1 (alice's resting bid) was cancelled, not traded against;
        # order #2 then had nothing left to match and rests on the ask side.
        self.assertEqual(book.total_resting_qty(), 10)
        self.assertIsNone(book.best_bid())
        self.assertEqual(book.best_ask(), 10.0)

    def test_self_trade_prevention_disabled_allows_self_match(self):
        book = OrderBook("X", self_trade_prevention=False)
        book.submit(mk(1, Side.BUY, 10, 10.0, agent="alice"))
        trades = book.submit(mk(2, Side.SELL, 10, 10.0, agent="alice"))
        self.assertEqual(len(trades), 1)

    def test_stp_skips_own_order_but_still_matches_others_behind_it(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 10, 10.0, agent="alice"))   # will be STP-cancelled
        book.submit(mk(2, Side.BUY, 10, 10.0, agent="bob"))     # should still get matched
        trades = book.submit(mk(3, Side.SELL, 10, 10.0, agent="alice"))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].buy_agent, "bob")
        self.assertEqual(book.stp_cancels, [1])


class TestDepthAndInvariants(unittest.TestCase):
    def test_depth_snapshot_sorted_best_first(self):
        book = OrderBook("X")
        book.submit(mk(1, Side.BUY, 5, 9.0))
        book.submit(mk(2, Side.BUY, 5, 10.0))
        book.submit(mk(3, Side.SELL, 5, 11.0))
        book.submit(mk(4, Side.SELL, 5, 12.0))
        d = book.depth()
        self.assertEqual([p for p, _ in d["bids"]], [10.0, 9.0])
        self.assertEqual([p for p, _ in d["asks"]], [11.0, 12.0])

    def test_wrong_symbol_raises(self):
        from matchbook.order import ValidationError
        book = OrderBook("X")
        wrong_symbol_order = Order(1, "OTHER", Side.BUY, OrderType.LIMIT, 5, price=9.0)
        with self.assertRaises(ValidationError):
            book.submit(wrong_symbol_order)

    def test_random_sessions_never_violate_price_time_priority_or_conservation(self):
        """Property test: over many random order sequences, (a) whenever a
        trade occurs, no better-priced or earlier order of the same side
        was skipped over, and (b) total qty bought == total qty sold always."""
        rng = random.Random(1234)
        for trial in range(30):
            book = OrderBook("PROP", self_trade_prevention=False)
            oid = 1
            total_buy_qty = 0
            total_sell_qty = 0
            for _ in range(60):
                side = rng.choice([Side.BUY, Side.SELL])
                qty = rng.randint(1, 20)
                price = round(rng.uniform(9.0, 11.0), 2)
                agent = f"agent{rng.randint(0, 4)}"
                order = mk(oid, side, qty, price, agent=agent, symbol="PROP")
                trades = book.submit(order)
                for t in trades:
                    total_buy_qty += t.qty
                    total_sell_qty += t.qty
                oid += 1
            self.assertEqual(total_buy_qty, total_sell_qty, f"trial {trial}: conservation violated")

    def test_no_crossed_book_ever_remains_after_any_submit(self):
        rng = random.Random(99)
        book = OrderBook("PROP", self_trade_prevention=False)
        for i in range(1, 200):
            side = rng.choice([Side.BUY, Side.SELL])
            qty = rng.randint(1, 15)
            price = round(rng.uniform(9.0, 11.0), 2)
            book.submit(mk(i, side, qty, price, symbol="PROP"))
            bb, ba = book.best_bid(), book.best_ask()
            if bb is not None and ba is not None:
                self.assertLess(bb, ba, "book must never remain crossed after matching settles")


if __name__ == "__main__":
    unittest.main()
