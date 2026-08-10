"""A deliberately naive, brute-force reference matcher.

`book.py`'s OrderBook keeps sorted price levels and O(1) cancel lookup
because it has to run a multi-thousand-tick simulation. That
sophistication is exactly what makes it easy to get subtly wrong. This
module re-implements the *same* price-time-priority matching semantics
the dumbest possible way — a flat list of every resting order, scanned
linearly for the best price every single time — so it can serve as an
independent ground truth for `fuzz.py` to differentially test the real
engine against. If the two ever disagree on the resulting trades or
final book state, the real engine has a bug, no matter how "obviously
correct" it looked.

This is deliberately NOT optimized. O(n) per operation is the point: the
simplicity is what makes correctness self-evident by inspection.
"""
from order import Side, OrderType
from book import RejectedOrder


class NaiveOrderBook:
    def __init__(self, symbol="X"):
        self.symbol = symbol
        self.resting = []  # flat list of Order objects, both sides mixed
        self.trades = []

    def _side_orders(self, side):
        return [o for o in self.resting if o.side is side and o.qty > 0]

    def best_bid(self):
        bids = self._side_orders(Side.BUY)
        return max((o.price for o in bids), default=None)

    def best_ask(self):
        asks = self._side_orders(Side.SELL)
        return min((o.price for o in asks), default=None)

    def depth(self, levels=10):
        def agg(side, reverse):
            orders = self._side_orders(side)
            by_price = {}
            for o in orders:
                by_price[o.price] = by_price.get(o.price, 0) + o.qty
            prices = sorted(by_price, reverse=reverse)[:levels]
            return [(p, by_price[p]) for p in prices]
        return {"bids": agg(Side.BUY, True), "asks": agg(Side.SELL, False)}

    def _best_opposite_order(self, side):
        """The single order that price-time priority says should fill
        next against an incoming order of the given side: best price,
        then earliest ts, found by a dumb linear scan of everything."""
        candidates = self._side_orders(side.opposite)
        if not candidates:
            return None
        if side is Side.BUY:
            best_price = min(o.price for o in candidates)
        else:
            best_price = max(o.price for o in candidates)
        at_best = [o for o in candidates if o.price == best_price]
        at_best.sort(key=lambda o: o.ts)
        return at_best[0]

    def _acceptable(self, order, resting_price):
        if order.otype is OrderType.MARKET or order.price is None:
            return True
        if order.side is Side.BUY:
            return resting_price <= order.price
        return resting_price >= order.price

    def _total_available(self, order):
        candidates = self._side_orders(order.side.opposite)
        total = 0
        for o in candidates:
            if self._acceptable(order, o.price):
                total += o.qty
        return total

    def submit(self, side, otype, qty, price=None, owner="?", order_id=None, ts=None):
        if qty <= 0:
            raise RejectedOrder(f"qty must be positive, got {qty}")
        if otype is OrderType.LIMIT and price is None:
            raise RejectedOrder("LIMIT order requires a price")
        if otype is OrderType.MARKET and price is not None:
            raise RejectedOrder("MARKET order must not specify a price")
        if price is not None and price <= 0:
            raise RejectedOrder(f"price must be positive, got {price}")

        from order import Order, Trade  # local import to avoid cycle at module load
        ts = 0 if ts is None else ts
        oid = order_id if order_id is not None else _naive_next_id()
        order = Order(id=oid, side=side, otype=otype, qty=qty, price=price, ts=ts, owner=owner)

        if otype is OrderType.FOK and self._total_available(order) < order.qty:
            return None, []

        trades = []
        while order.qty > 0:
            best = self._best_opposite_order(order.side)
            if best is None or not self._acceptable(order, best.price):
                break
            if best.owner == order.owner:
                # same self-trade-prevention policy as the real engine:
                # cancel the resting order, don't match it, keep scanning.
                best.qty = 0
                continue
            fill_qty = min(order.qty, best.qty)
            trades.append(Trade(
                price=best.price, qty=fill_qty, ts=order.ts, aggressor_side=order.side,
                maker_order_id=best.id, taker_order_id=order.id,
                maker_owner=best.owner, taker_owner=order.owner,
            ))
            order.qty -= fill_qty
            best.qty -= fill_qty

        self.resting = [o for o in self.resting if o.qty > 0]
        self.trades.extend(trades)

        resting_order = None
        if order.qty > 0 and otype is OrderType.LIMIT:
            self.resting.append(order)
            resting_order = order
        return resting_order, trades

    def cancel(self, order_id):
        for o in self.resting:
            if o.id == order_id and o.qty > 0:
                o.qty = 0
                self.resting = [x for x in self.resting if x.qty > 0]
                return True
        return False


_naive_id_seq = [10**9]  # disjoint id space from order.py's counter, for standalone use


def _naive_next_id():
    _naive_id_seq[0] += 1
    return _naive_id_seq[0]
