"""A price-time-priority limit order book matching engine.

This is the real algorithm every electronic exchange runs: orders on each
side are grouped by price level, each level is FIFO (first order in at a
price is the first one filled at that price), and a new order matches
against the *best* opposite price(s) first, walking price levels outward
until it is filled or the book runs out of liquidity at an acceptable
price.

Invariants this module guarantees (see tests/test_book.py):
  * The book never crosses: best_bid() < best_ask() at all times.
  * Volume is conserved: every trade removes exactly `qty` from the
    maker order and exactly `qty` from the taker order.
  * FIFO time priority is respected within a price level.
  * Cancelling an order removes exactly that order and nothing else.
"""
import bisect
from collections import deque

from order import Order, Trade, Side, OrderType


class RejectedOrder(Exception):
    """Raised for malformed order requests (bad qty/price/type)."""


class OrderBook:
    def __init__(self, symbol="X"):
        self.symbol = symbol
        # price -> deque[Order], FIFO within a price level
        self.bids = {}
        self.asks = {}
        # kept sorted ascending; best bid = bid_prices[-1], best ask = ask_prices[0]
        self.bid_prices = []
        self.ask_prices = []
        self.orders = {}  # order_id -> Order, for O(1) cancel lookup
        self.trades = []  # full trade tape for this book
        self._tick = 0

    # ---- price-level bookkeeping -----------------------------------
    def _levels_for(self, side):
        return (self.bids, self.bid_prices) if side is Side.BUY else (self.asks, self.ask_prices)

    def _insert_resting(self, order):
        levels, prices = self._levels_for(order.side)
        if order.price not in levels:
            levels[order.price] = deque()
            bisect.insort(prices, order.price)
        levels[order.price].append(order)
        self.orders[order.id] = order

    def _remove_price_if_empty(self, side, price):
        levels, prices = self._levels_for(side)
        if price in levels and not levels[price]:
            del levels[price]
            i = bisect.bisect_left(prices, price)
            if i < len(prices) and prices[i] == price:
                prices.pop(i)

    def best_bid(self):
        return self.bid_prices[-1] if self.bid_prices else None

    def best_ask(self):
        return self.ask_prices[0] if self.ask_prices else None

    def mid_price(self):
        bb, ba = self.best_bid(), self.best_ask()
        if bb is not None and ba is not None:
            return (bb + ba) / 2
        return bb if bb is not None else ba

    def spread(self):
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return ba - bb

    def depth(self, levels=10):
        """Top-N price levels each side, best-first: [(price, total_qty), ...]."""
        bid_view = [(p, sum(o.qty for o in self.bids[p])) for p in reversed(self.bid_prices[-levels:])]
        ask_view = [(p, sum(o.qty for o in self.asks[p])) for p in self.ask_prices[:levels]]
        return {"bids": bid_view, "asks": ask_view}

    # ---- order submission -------------------------------------------
    def submit(self, side, otype, qty, price=None, owner="?", order_id=None, ts=None):
        """Submit a new order. Returns (order_or_None, trades).

        order_or_None is the resting Order if any quantity is left on the
        book after matching (LIMIT only), else None.
        """
        if qty <= 0:
            raise RejectedOrder(f"qty must be positive, got {qty}")
        if otype is OrderType.LIMIT and price is None:
            raise RejectedOrder("LIMIT order requires a price")
        if otype is not OrderType.LIMIT and price is not None and otype not in (OrderType.IOC, OrderType.FOK):
            raise RejectedOrder(f"{otype} order must not specify a price")

        ts = self._tick if ts is None else ts
        oid = order_id if order_id is not None else _fallback_id(self)
        order = Order(id=oid, side=side, otype=otype, qty=qty, price=price, ts=ts, owner=owner)

        if otype is OrderType.FOK and not self._can_fully_fill(order):
            return None, []  # kill: no trades, nothing rests

        trades = self._match(order)

        resting = None
        if order.qty > 0 and otype is OrderType.LIMIT:
            self._insert_resting(order)
            resting = order
        # MARKET/IOC/FOK: any unfilled remainder is simply discarded (not resting)
        return resting, trades

    def _can_fully_fill(self, order):
        """Non-mutating check: is there enough acceptable-price liquidity
        on the opposite side to fill `order` completely right now?"""
        levels, prices = self._levels_for(order.side.opposite)
        available = 0
        if order.side is Side.BUY:
            for p in prices:  # ascending; walk from best ask (lowest) up
                if order.price is not None and p > order.price:
                    break
                available += sum(o.qty for o in levels[p])
                if available >= order.qty:
                    return True
        else:
            for p in reversed(prices):  # descending; walk from best bid (highest) down
                if order.price is not None and p < order.price:
                    break
                available += sum(o.qty for o in levels[p])
                if available >= order.qty:
                    return True
        return available >= order.qty

    def _price_acceptable(self, order, level_price):
        if order.otype is OrderType.MARKET or order.price is None:
            return True
        if order.side is Side.BUY:
            return level_price <= order.price
        return level_price >= order.price

    def _match(self, order):
        trades = []
        levels, prices = self._levels_for(order.side.opposite)

        while order.qty > 0 and prices:
            best_price = prices[0] if order.side is Side.BUY else prices[-1]
            if not self._price_acceptable(order, best_price):
                break
            dq = levels[best_price]
            while dq and order.qty > 0:
                maker = dq[0]
                fill_qty = min(order.qty, maker.qty)
                trade = Trade(
                    price=best_price,
                    qty=fill_qty,
                    ts=order.ts,
                    aggressor_side=order.side,
                    maker_order_id=maker.id,
                    taker_order_id=order.id,
                    maker_owner=maker.owner,
                    taker_owner=order.owner,
                )
                trades.append(trade)
                order.qty -= fill_qty
                maker.qty -= fill_qty
                if maker.qty == 0:
                    dq.popleft()
                    del self.orders[maker.id]
            if not dq:
                self._remove_price_if_empty(order.side.opposite, best_price)
        self.trades.extend(trades)
        return trades

    # ---- cancel --------------------------------------------------------
    def cancel(self, order_id):
        order = self.orders.get(order_id)
        if order is None:
            return False
        levels, prices = self._levels_for(order.side)
        dq = levels.get(order.price)
        if dq is None:
            return False
        try:
            dq.remove(order)
        except ValueError:
            return False
        del self.orders[order_id]
        self._remove_price_if_empty(order.side, order.price)
        return True

    def open_orders_of(self, owner):
        return [o for o in self.orders.values() if o.owner == owner]

    def tick(self, t):
        self._tick = t


def _fallback_id(book):
    from order import next_order_id
    return next_order_id()
