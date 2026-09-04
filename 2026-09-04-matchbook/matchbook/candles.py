"""Aggregate a symbol's trade tape into OHLCV bars.

There is no wall clock in this simulator -- "time" is the monotonic order
arrival sequence number every order and trade already carries (`seq`). A bar
groups together every trade whose aggressor order arrived within the same
`bar_size`-wide slice of that sequence axis, which makes candle aggregation
exactly reproducible from the trade tape alone, with no separate clock to
keep in sync.
"""
from __future__ import annotations

from dataclasses import dataclass

from .order import Trade


@dataclass
class Candle:
    bucket: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    trades: int

    def to_dict(self) -> dict:
        return {
            "bucket": self.bucket,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trades": self.trades,
        }


def build_candles(trades: list[Trade], symbol: str, bar_size: int = 10) -> list[Candle]:
    if bar_size <= 0:
        raise ValueError(f"bar_size must be positive, got {bar_size}")
    symbol_trades = sorted((t for t in trades if t.symbol == symbol), key=lambda t: (t.seq, t.trade_id))
    bars: dict[int, Candle] = {}
    for t in symbol_trades:
        bucket = t.seq // bar_size
        c = bars.get(bucket)
        if c is None:
            bars[bucket] = Candle(
                bucket=bucket, open=t.price, high=t.price, low=t.price, close=t.price,
                volume=t.qty, trades=1,
            )
        else:
            c.high = max(c.high, t.price)
            c.low = min(c.low, t.price)
            c.close = t.price
            c.volume += t.qty
            c.trades += 1
    return [bars[k] for k in sorted(bars)]
