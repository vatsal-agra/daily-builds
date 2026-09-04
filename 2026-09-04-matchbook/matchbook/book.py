"""The core matching engine: a single-symbol price-time-priority limit order book.

This is the real algorithm behind every electronic exchange's matching core:

  - Resting orders are grouped into price levels; each level is a FIFO queue
    (time priority within a price).
  - Bids are matched best-price-first (highest first); asks best-price-first
    (lowest first) -- price priority across levels.
  - An incoming ("aggressor") order walks the opposite side of the book,
    consuming resting ("maker") liquidity level by level, queue-order within
    a level, until it is filled or no more liquidity crosses its price.
  - Execution price is always the *resting* (maker's) price -- the aggressor
    never pays worse than what was quoted, and often better.

Two heaps (bids: negated-price max-heap, asks: plain min-heap) give O(log n)
best-price lookup with lazy deletion: a price can linger in the heap after
its level empties, and is discarded the moment it reaches the top and is
found empty.
"""
from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field

from .order import Order, OrderStatus, OrderType, Side, Trade, TimeInForce, ValidationError


@dataclass
class PriceLevel:
    price: float
    orders: deque = field(default_factory=deque)

    @property
    def total_qty(self) -> int:
        return sum(o.remaining_qty for o in self.orders)


class OrderBook:
    """A single-symbol limit order book."""

    def __init__(self, symbol: str, self_trade_prevention: bool = True):
        self.symbol = symbol
        self.self_trade_prevention = self_trade_prevention

        # price -> PriceLevel, plus a lazily-cleaned heap of prices per side.
        self.bid_levels: dict[float, PriceLevel] = {}
        self.ask_levels: dict[float, PriceLevel] = {}
        self._bids_heap: list[float] = []   # store as -price for a max-heap
        self._asks_heap: list[float] = []   # plain min-heap

        self.orders: dict[int, Order] = {}  # currently-resting orders only
        self._trade_seq = 0
        self.stp_cancels: list[int] = []    # order_ids cancelled by STP, most-recent session

    # ------------------------------------------------------------------ #
    # Best-price bookkeeping (lazy heap cleanup)
    # ------------------------------------------------------------------ #
    def best_bid(self) -> float | None:
        while self._bids_heap:
            p = -self._bids_heap[0]
            level = self.bid_levels.get(p)
            if level and level.orders:
                return p
            heapq.heappop(self._bids_heap)
            self.bid_levels.pop(p, None)
        return None

    def best_ask(self) -> float | None:
        while self._asks_heap:
            p = self._asks_heap[0]
            level = self.ask_levels.get(p)
            if level and level.orders:
                return p
            heapq.heappop(self._asks_heap)
            self.ask_levels.pop(p, None)
        return None

    def spread(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return ba - bb

    def mid_price(self) -> float | None:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None and ba is None:
            return None
        if bb is None:
            return ba
        if ba is None:
            return bb
        return (bb + ba) / 2.0

    # ------------------------------------------------------------------ #
    # Depth snapshot (for the visualizer / agents' market view)
    # ------------------------------------------------------------------ #
    def depth(self, n: int = 10) -> dict:
        bid_prices = sorted(
            (p for p, lv in self.bid_levels.items() if lv.orders), reverse=True
        )[:n]
        ask_prices = sorted((p for p, lv in self.ask_levels.items() if lv.orders))[:n]
        return {
            "bids": [(p, self.bid_levels[p].total_qty) for p in bid_prices],
            "asks": [(p, self.ask_levels[p].total_qty) for p in ask_prices],
        }

    # ------------------------------------------------------------------ #
    # Order entry
    # ------------------------------------------------------------------ #
    def submit(self, order: Order) -> list[Trade]:
        """Submit a new order. Returns the list of trades it generated
        (empty if it rested untouched, or was cancelled/rejected outright)."""
        if order.symbol != self.symbol:
            raise ValidationError(
                f"order {order.order_id} is for symbol {order.symbol!r}, "
                f"book is {self.symbol!r}"
            )

        if order.tif == TimeInForce.FOK and not self._can_fully_fill(order):
            order.status = OrderStatus.REJECTED
            return []

        trades = self._match(order)

        if order.remaining_qty > 0:
            if order.order_type == OrderType.LIMIT and order.tif == TimeInForce.GTC:
                order.status = OrderStatus.OPEN
                self._rest(order)
            else:
                # MARKET, IOC, or (unreachable) FOK remainder: never rests.
                order.status = (
                    OrderStatus.CANCELLED if not trades else OrderStatus.PARTIALLY_FILLED
                )
        else:
            order.status = OrderStatus.FILLED

        return trades

    def cancel(self, order_id: int) -> bool:
        """Cancel a resting order. Returns True if it was found and removed."""
        order = self.orders.pop(order_id, None)
        if order is None:
            return False
        levels = self.bid_levels if order.side == Side.BUY else self.ask_levels
        level = levels.get(order.price)
        if level is not None:
            try:
                level.orders.remove(order)
            except ValueError:
                pass
        order.status = OrderStatus.CANCELLED
        return True

    def modify(self, order_id: int, new_price: float | None = None, new_qty: int | None = None) -> Order | None:
        """Cancel/replace: any price or quantity change loses time priority,
        matching real-exchange semantics -- implemented as cancel + re-submit
        as a brand-new resting order (same order_id, fresh queue position)."""
        old = self.orders.get(order_id)
        if old is None:
            return None
        self.cancel(order_id)
        price = new_price if new_price is not None else old.price
        qty = new_qty if new_qty is not None else old.remaining_qty
        replacement = Order(
            order_id=order_id,
            symbol=old.symbol,
            side=old.side,
            order_type=OrderType.LIMIT,
            qty=qty,
            price=price,
            tif=TimeInForce.GTC,
            agent_id=old.agent_id,
            seq=old.seq,
        )
        self.submit(replacement)
        return replacement

    # ------------------------------------------------------------------ #
    # Internal matching
    # ------------------------------------------------------------------ #
    def _crosses(self, order: Order, opposite_price: float | None) -> bool:
        if opposite_price is None:
            return False
        if order.order_type == OrderType.MARKET:
            return True
        if order.side == Side.BUY:
            return order.price >= opposite_price
        return order.price <= opposite_price

    def _match(self, order: Order) -> list[Trade]:
        trades: list[Trade] = []
        self.stp_cancels = []
        opposite_levels = self.ask_levels if order.side == Side.BUY else self.bid_levels
        best_fn = self.best_ask if order.side == Side.BUY else self.best_bid

        while order.remaining_qty > 0:
            best_price = best_fn()
            if not self._crosses(order, best_price):
                break
            level = opposite_levels[best_price]

            while level.orders and order.remaining_qty > 0:
                resting = level.orders[0]
                if (
                    self.self_trade_prevention
                    and order.agent_id
                    and resting.agent_id == order.agent_id
                ):
                    # Cancel-resting self-trade-prevention policy: drop the
                    # resting order (no trade) and keep walking the queue.
                    level.orders.popleft()
                    self.orders.pop(resting.order_id, None)
                    resting.status = OrderStatus.CANCELLED
                    self.stp_cancels.append(resting.order_id)
                    continue

                fill_qty = min(order.remaining_qty, resting.remaining_qty)
                trade_price = resting.price
                self._trade_seq += 1
                buy_order, sell_order = (
                    (order, resting) if order.side == Side.BUY else (resting, order)
                )
                trades.append(
                    Trade(
                        trade_id=self._trade_seq,
                        symbol=self.symbol,
                        price=trade_price,
                        qty=fill_qty,
                        buy_order_id=buy_order.order_id,
                        sell_order_id=sell_order.order_id,
                        buy_agent=buy_order.agent_id,
                        sell_agent=sell_order.agent_id,
                        aggressor_side=order.side,
                        seq=order.seq,
                    )
                )
                order.remaining_qty -= fill_qty
                resting.remaining_qty -= fill_qty
                if resting.remaining_qty == 0:
                    level.orders.popleft()
                    self.orders.pop(resting.order_id, None)
                    resting.status = OrderStatus.FILLED
                else:
                    resting.status = OrderStatus.PARTIALLY_FILLED

            if not level.orders:
                # Level exhausted; the lazy heap cleanup will drop its price
                # next time best_fn() is called.
                opposite_levels.pop(best_price, None)

        return trades

    def _can_fully_fill(self, order: Order) -> bool:
        """FOK pre-check: would `order` fill completely against the book as
        it stands right now, without mutating anything? Self-trade-prevented
        liquidity is excluded, matching what `_match` would actually do."""
        if order.order_type == OrderType.MARKET:
            price_ok = lambda p: True
        elif order.side == Side.BUY:
            price_ok = lambda p: order.price >= p
        else:
            price_ok = lambda p: order.price <= p

        if order.side == Side.BUY:
            prices = sorted(p for p, lv in self.ask_levels.items() if lv.orders)
        else:
            prices = sorted((p for p, lv in self.bid_levels.items() if lv.orders), reverse=True)

        levels = self.ask_levels if order.side == Side.BUY else self.bid_levels
        remaining = order.remaining_qty
        for p in prices:
            if not price_ok(p):
                break
            for resting in levels[p].orders:
                if self.self_trade_prevention and order.agent_id and resting.agent_id == order.agent_id:
                    continue
                remaining -= resting.remaining_qty
                if remaining <= 0:
                    return True
        return remaining <= 0

    def _rest(self, order: Order) -> None:
        levels = self.bid_levels if order.side == Side.BUY else self.ask_levels
        heap = self._bids_heap if order.side == Side.BUY else self._asks_heap
        level = levels.get(order.price)
        if level is None:
            level = PriceLevel(price=order.price)
            levels[order.price] = level
            heapq.heappush(heap, -order.price if order.side == Side.BUY else order.price)
        level.orders.append(order)
        self.orders[order.order_id] = order

    # ------------------------------------------------------------------ #
    # Introspection / invariant checking (used heavily by the test suite)
    # ------------------------------------------------------------------ #
    def all_resting_orders(self) -> list[Order]:
        return list(self.orders.values())

    def total_resting_qty(self) -> int:
        return sum(o.remaining_qty for o in self.orders.values())
