import unittest

from matchbook.candles import build_candles
from matchbook.order import Side, Trade


def t(seq, price, qty, symbol="X", trade_id=None):
    return Trade(
        trade_id=trade_id if trade_id is not None else seq,
        symbol=symbol, price=price, qty=qty,
        buy_order_id=1, sell_order_id=2, buy_agent="a", sell_agent="b",
        aggressor_side=Side.BUY, seq=seq,
    )


class TestCandles(unittest.TestCase):
    def test_empty_trades_gives_no_candles(self):
        self.assertEqual(build_candles([], "X", bar_size=10), [])

    def test_single_bucket_ohlcv(self):
        trades = [t(0, 10.0, 5), t(3, 11.0, 5), t(5, 9.0, 5), t(9, 10.5, 5)]
        candles = build_candles(trades, "X", bar_size=10)
        self.assertEqual(len(candles), 1)
        c = candles[0]
        self.assertEqual((c.open, c.high, c.low, c.close), (10.0, 11.0, 9.0, 10.5))
        self.assertEqual(c.volume, 20)
        self.assertEqual(c.trades, 4)

    def test_splits_into_multiple_buckets(self):
        trades = [t(0, 10.0, 1), t(11, 12.0, 1), t(25, 8.0, 1)]
        candles = build_candles(trades, "X", bar_size=10)
        self.assertEqual([c.bucket for c in candles], [0, 1, 2])

    def test_filters_by_symbol(self):
        trades = [t(0, 10.0, 1, symbol="X"), t(1, 99.0, 1, symbol="Y")]
        candles = build_candles(trades, "X", bar_size=10)
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].close, 10.0)

    def test_unsorted_input_still_orders_correctly(self):
        trades = [t(5, 20.0, 1), t(1, 10.0, 1), t(3, 15.0, 1)]
        candles = build_candles(trades, "X", bar_size=10)
        self.assertEqual(candles[0].open, 10.0)
        self.assertEqual(candles[0].close, 20.0)

    def test_invalid_bar_size_raises(self):
        with self.assertRaises(ValueError):
            build_candles([t(0, 10.0, 1)], "X", bar_size=0)


if __name__ == "__main__":
    unittest.main()
