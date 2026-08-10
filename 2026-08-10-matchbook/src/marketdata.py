"""Market data derived from the matching engine's real output.

Nothing here is fabricated: candles are built strictly from the recorded
trade tape, and depth snapshots are copies of what `OrderBook.depth()`
actually returned at that tick. This module never invents a price.
"""
from dataclasses import dataclass, asdict


@dataclass
class Candle:
    t_start: int
    t_end: int
    open: int
    high: int
    low: int
    close: int
    volume: int
    n_trades: int


def build_candles(trades, bar_ticks):
    """Aggregate a trade tape (list[Trade], already sorted by ts) into
    fixed-width OHLCV bars of `bar_ticks` simulated ticks each. Bars with
    zero trades are skipped (no fabricated flat candle)."""
    if not trades:
        return []
    candles = []
    bucket = {}
    bucket_start = None

    def flush():
        if bucket:
            candles.append(Candle(
                t_start=bucket_start,
                t_end=bucket_start + bar_ticks - 1,
                open=bucket["open"],
                high=bucket["high"],
                low=bucket["low"],
                close=bucket["close"],
                volume=bucket["volume"],
                n_trades=bucket["n"],
            ))

    for tr in trades:
        this_start = (tr.ts // bar_ticks) * bar_ticks
        if bucket_start is None:
            bucket_start = this_start
        if this_start != bucket_start:
            flush()
            bucket.clear()
            bucket_start = this_start
        if not bucket:
            bucket.update(open=tr.price, high=tr.price, low=tr.price, close=tr.price, volume=0, n=0)
        bucket["high"] = max(bucket["high"], tr.price)
        bucket["low"] = min(bucket["low"], tr.price)
        bucket["close"] = tr.price
        bucket["volume"] += tr.qty
        bucket["n"] += 1
    flush()
    return candles


def candles_to_dicts(candles):
    return [asdict(c) for c in candles]


class DepthRecorder:
    """Captures a periodic time series of book depth snapshots, so the
    visualizer can scrub through how the ladder actually looked over the
    session instead of only seeing the final state."""

    def __init__(self, every_n_ticks=5, levels=8):
        self.every_n_ticks = every_n_ticks
        self.levels = levels
        self.snapshots = []  # list of {"t":, "bids": [...], "asks": [...]}

    def maybe_record(self, book, t):
        if t % self.every_n_ticks != 0:
            return
        d = book.depth(self.levels)
        self.snapshots.append({"t": t, "bids": d["bids"], "asks": d["asks"]})
