import unittest
import _pathsetup  # noqa: F401

from order import Side, Trade
from book import OrderBook, OrderType
from marketdata import build_candles, DepthRecorder


def trade(price, qty, ts):
    return Trade(price=price, qty=qty, ts=ts, aggressor_side=Side.BUY,
                 maker_order_id=1, taker_order_id=2, maker_owner="a", taker_owner="b")


class TestCandles(unittest.TestCase):
    def test_empty_trade_list_yields_no_candles(self):
        self.assertEqual(build_candles([], bar_ticks=10), [])

    def test_single_bucket_ohlc_correct(self):
        trades = [trade(100, 5, 0), trade(110, 3, 2), trade(95, 2, 4), trade(105, 1, 6)]
        candles = build_candles(trades, bar_ticks=10)
        self.assertEqual(len(candles), 1)
        c = candles[0]
        self.assertEqual(c.open, 100)
        self.assertEqual(c.high, 110)
        self.assertEqual(c.low, 95)
        self.assertEqual(c.close, 105)
        self.assertEqual(c.volume, 11)
        self.assertEqual(c.n_trades, 4)

    def test_splits_across_bucket_boundary(self):
        trades = [trade(100, 1, 0), trade(101, 1, 9), trade(200, 1, 10), trade(201, 1, 15)]
        candles = build_candles(trades, bar_ticks=10)
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0].t_start, 0)
        self.assertEqual(candles[1].t_start, 10)

    def test_no_fabricated_flat_candles_for_silent_periods(self):
        # a gap with zero trades must not produce a synthetic flat candle
        trades = [trade(100, 1, 0), trade(100, 1, 500)]
        candles = build_candles(trades, bar_ticks=10)
        self.assertEqual(len(candles), 2)  # not 51 (the number of 10-tick buckets spanned)


class TestDepthRecorder(unittest.TestCase):
    def test_records_only_on_period_and_matches_live_book(self):
        book = OrderBook("X")
        book.submit(Side.BUY, OrderType.LIMIT, 5, price=99, owner="a")
        rec = DepthRecorder(every_n_ticks=5, levels=3)
        for t in range(1, 12):
            book.tick(t)
            rec.maybe_record(book, t)
        self.assertEqual([s["t"] for s in rec.snapshots], [5, 10])
        self.assertEqual(rec.snapshots[0]["bids"], book.depth(3)["bids"])


if __name__ == "__main__":
    unittest.main()
