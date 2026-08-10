"""Trading agents.

Every agent implements the same tiny interface: `on_tick(view, rng) ->
list[Action]`. No agent is ever handed the simulator's "true" fair value
— only what a real trader could see: the book's current depth, its own
open orders and inventory, and the public trade tape. Whatever price
behavior emerges (trends, mean reversion, spread capture) is a genuine
consequence of the strategies interacting, not scripted.

Action is a tiny tagged tuple-like dataclass so the simulator doesn't
need to know each strategy's internals: ("place", side, otype, qty,
price) or ("cancel", order_id).
"""
from dataclasses import dataclass
from order import Side, OrderType


@dataclass
class BookView:
    """Read-only snapshot an agent is allowed to see on a given tick."""
    symbol: str
    tick: int
    best_bid: int
    best_ask: int
    depth: dict                 # {"bids": [(price, qty)...], "asks": [...]}
    recent_trades: list         # most-recent-last, capped window of Trade
    my_open_orders: list        # this agent's own resting Order objects
    my_inventory: int           # net position (signed)
    my_cash: int                # cash ticks (signed, negative = owes)
    other_symbol_view: "BookView" = None  # only populated for stat-arb


@dataclass
class Action:
    kind: str          # "place" | "cancel"
    side: Side = None
    otype: OrderType = None
    qty: int = None
    price: int = None
    order_id: int = None
    symbol: str = None  # which book this targets; None = the agent's primary book


class Agent:
    """Base class every strategy subclasses. `name` is used for
    ownership attribution in trades and the P&L leaderboard."""

    def __init__(self, name):
        self.name = name

    def on_tick(self, view, rng):
        raise NotImplementedError


class NoiseTrader(Agent):
    """Background liquidity: places small random limit orders near the
    current mid price, occasionally crossing the spread with a market
    order. Without this, a book seeded with only "smart" agents can
    starve for liquidity and lock up. Real exchanges always have this
    background flow (retail, uninformed order flow)."""

    def __init__(self, name, mid_guess=10000, band=150, place_prob=0.55, drift_step=2, cross_prob=0.12):
        super().__init__(name)
        self.mid_guess = mid_guess
        self.band = band
        self.place_prob = place_prob
        self.drift_step = drift_step
        self.cross_prob = cross_prob  # fraction of the time this trader takes liquidity instead of providing it

    def on_tick(self, view, rng):
        actions = []
        # the anchor itself takes a slow, persistent random walk every
        # tick (not just when we trade) — this is the only source of
        # organic price drift in the whole simulation; every trend or
        # reversal the momentum/mean-reversion agents react to bottoms
        # out in this one random walk plus the noise this agent adds.
        self.mid_guess = max(1, self.mid_guess + rng.randint(-self.drift_step, self.drift_step))

        # keep a bounded number of resting orders — cancel a random stale
        # one most ticks, and force cancellation once our own book of
        # orders gets too deep, so the book doesn't grow without bound
        # over a long session.
        if view.my_open_orders and (rng.random() < 0.35 or len(view.my_open_orders) > 25):
            stale = rng.choice(view.my_open_orders)
            actions.append(Action("cancel", order_id=stale.id))

        if rng.random() > self.place_prob:
            return actions

        # Most of the time this trader provides passive liquidity (a
        # resting limit order priced away from mid). A minority of the
        # time it takes liquidity instead, crossing the spread with a
        # small market order — real uninformed/retail order flow does
        # both, and without this a lone noise trader against a static
        # seeded book can never generate a single trade: its passive buy
        # orders always price below mid and its passive sells always
        # price above mid, so by construction they can never cross each
        # other or the resting book.
        if rng.random() < self.cross_prob and view.best_bid is not None and view.best_ask is not None:
            side = rng.choice([Side.BUY, Side.SELL])
            qty = rng.randint(1, 5)
            return actions + [Action("place", side=side, otype=OrderType.MARKET, qty=qty)]

        if view.best_bid is not None and view.best_ask is not None:
            mid = (view.best_bid + view.best_ask) // 2
        else:
            mid = None
        if mid is None:
            mid = self.mid_guess
        else:
            # blend toward the wandering anchor so the market can't fully
            # decouple from it, but still respects real book pressure
            mid = (mid + self.mid_guess) // 2
        side = rng.choice([Side.BUY, Side.SELL])
        offset = rng.randint(1, self.band)
        price = mid - offset if side is Side.BUY else mid + offset
        qty = rng.randint(1, 8)
        actions.append(Action("place", side=side, otype=OrderType.LIMIT, qty=qty, price=max(1, price)))
        return actions


class MarketMaker(Agent):
    """Quotes both sides around its own estimate of fair value, captures
    the spread, and skews its quotes away from its own inventory (if it's
    long, it prices its ask more aggressively and its bid less
    aggressively) so inventory mean-reverts toward zero instead of
    accumulating without bound — the textbook Avellaneda-Stoikov
    intuition, simplified to a linear skew."""

    def __init__(self, name, min_edge=6, quote_qty=10, inventory_skew=4, max_inventory=400):
        super().__init__(name)
        self.min_edge = min_edge          # smallest half-spread we'll ever quote (must stay profitable)
        self.quote_qty = quote_qty
        self.inventory_skew = inventory_skew
        self.max_inventory = max_inventory
        self._fair = None

    def on_tick(self, view, rng):
        actions = [Action("cancel", order_id=o.id) for o in view.my_open_orders]

        if view.recent_trades:
            self._fair = view.recent_trades[-1].price
        elif view.best_bid and view.best_ask:
            self._fair = (view.best_bid + view.best_ask) // 2
        if self._fair is None:
            return actions  # no price discovery yet, sit out

        skew = -self.inventory_skew * view.my_inventory // 10
        bid_ceiling = self._fair - self.min_edge + skew   # never bid above this (stays profitable)
        ask_floor = self._fair + self.min_edge + skew     # never ask below this

        # "join and improve": quote one tick better than the current best
        # if that's still profitable, so we actually win price-time
        # priority instead of resting behind tighter background flow —
        # but never cross our own profitability ceiling/floor.
        bid_price = bid_ceiling
        if view.best_bid is not None:
            bid_price = min(bid_ceiling, view.best_bid + 1)
        ask_price = ask_floor
        if view.best_ask is not None:
            ask_price = max(ask_floor, view.best_ask - 1)
        bid_price = max(1, bid_price)
        ask_price = max(bid_price + 1, ask_price)  # never let our own quote cross itself

        if view.my_inventory < self.max_inventory:
            actions.append(Action("place", side=Side.BUY, otype=OrderType.LIMIT,
                                   qty=self.quote_qty, price=bid_price))
        if view.my_inventory > -self.max_inventory:
            actions.append(Action("place", side=Side.SELL, otype=OrderType.LIMIT,
                                   qty=self.quote_qty, price=ask_price))
        return actions


class MomentumTrader(Agent):
    """Tracks a short and a long moving average of trade prices. When the
    short MA crosses meaningfully above the long MA it buys (trend is up);
    below, it sells. Trades with aggressive IOC orders that cross the
    spread, since a momentum trader wants execution now, not to sit
    passively and miss the move."""

    def __init__(self, name, short_n=5, long_n=20, threshold=8, qty=6):
        super().__init__(name)
        self.short_n = short_n
        self.long_n = long_n
        self.threshold = threshold
        self.qty = qty

    def on_tick(self, view, rng):
        prices = [t.price for t in view.recent_trades]
        if len(prices) < self.long_n:
            return []
        short_ma = sum(prices[-self.short_n:]) / self.short_n
        long_ma = sum(prices[-self.long_n:]) / self.long_n
        signal = short_ma - long_ma
        if abs(signal) < self.threshold:
            return []
        side = Side.BUY if signal > 0 else Side.SELL
        return [Action("place", side=side, otype=OrderType.IOC, qty=self.qty)]


class MeanReversionTrader(Agent):
    """Opposite instinct from the momentum trader: tracks a longer moving
    average as its estimate of "fair", and when the *last* trade price
    strays far from it, bets on reversion back toward the average."""

    def __init__(self, name, window=30, threshold=20, qty=6):
        super().__init__(name)
        self.window = window
        self.threshold = threshold
        self.qty = qty

    def on_tick(self, view, rng):
        prices = [t.price for t in view.recent_trades]
        if len(prices) < self.window:
            return []
        avg = sum(prices[-self.window:]) / self.window
        last = prices[-1]
        deviation = last - avg
        if abs(deviation) < self.threshold:
            return []
        # price is above fair -> sell (expect reversion down); below -> buy
        side = Side.SELL if deviation > 0 else Side.BUY
        return [Action("place", side=side, otype=OrderType.IOC, qty=self.qty)]


class StatArbTrader(Agent):
    """Stretch-feature agent: trades the *spread* between two correlated
    instruments at once (`view` is instrument A, `view.other_symbol_view`
    is B — the simulator registers this agent as "primary" on A only, and
    routes its actions to whichever book each Action.symbol names). When
    A trades rich relative to B by more than `threshold` versus their
    trailing average spread, it sells A and buys B in the same tick,
    betting the pair reverts — classic pairs trading, and a real
    demonstration of the pluggable Agent SDK acting across two books at
    once, something none of the single-instrument strategies do."""

    def __init__(self, name, window=25, threshold=18, qty=5):
        super().__init__(name)
        self.window = window
        self.threshold = threshold
        self.qty = qty
        self._spread_hist = []

    def on_tick(self, view, rng):
        other = view.other_symbol_view
        if other is None or not view.recent_trades or not other.recent_trades:
            return []
        a_price = view.recent_trades[-1].price
        b_price = other.recent_trades[-1].price
        spread = a_price - b_price
        self._spread_hist.append(spread)
        if len(self._spread_hist) < self.window:
            return []
        avg = sum(self._spread_hist[-self.window:]) / self.window
        dev = spread - avg
        if abs(dev) < self.threshold:
            return []
        # A is rich relative to its trailing spread average -> sell A, buy
        # B in the same tick (both legs, one decision) betting on reversion.
        if dev > 0:
            a_side, b_side = Side.SELL, Side.BUY
        else:
            a_side, b_side = Side.BUY, Side.SELL
        return [
            Action("place", side=a_side, otype=OrderType.IOC, qty=self.qty, symbol=view.symbol),
            Action("place", side=b_side, otype=OrderType.IOC, qty=self.qty, symbol=other.symbol),
        ]
