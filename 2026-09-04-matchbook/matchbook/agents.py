"""Trading agent strategies. Each agent only ever sees *public* market state
(the book's depth and the trade tape) except `InformedTrader`, which alone
is given a peek at a private fundamental-value signal that the rest of the
market has to discover the hard way -- by watching where trades actually
print. None of them are scripted to produce any particular price path; the
path is whatever falls out of their independent decisions colliding in the
order book.

Every agent is driven by a single shared `random.Random` the `Simulator`
owns, so a fixed seed reproduces an entire session bit-for-bit.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .engine import Exchange
from .order import OrderType, Side, TimeInForce


class Agent:
    agent_id: str
    symbols: list[str]

    def act(self, exchange: Exchange, rng: random.Random, tick: int) -> None:
        raise NotImplementedError


def _round_tick(price: float, tick_size: float = 0.01) -> float:
    return round(round(price / tick_size) * tick_size, 2)


@dataclass
class MarketMaker(Agent):
    """Quotes both sides of the book every tick, skewing its quotes against
    its own inventory so it mean-reverts toward a flat position instead of
    accumulating unbounded risk -- the textbook Avellaneda-Stoikov intuition
    (skew quotes away from your inventory) without the full stochastic
    control machinery."""

    agent_id: str
    symbols: list[str]
    half_spread: float = 0.10
    quote_size: int = 40
    inventory_skew: float = 0.02     # price adjustment per unit of inventory
    requote_every: int = 1
    _quote_ids: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    _fair_value: dict[str, float] = field(default_factory=dict)

    def set_initial_fair_value(self, symbol: str, price: float) -> None:
        self._fair_value.setdefault(symbol, price)

    def act(self, exchange: Exchange, rng: random.Random, tick: int) -> None:
        if tick % self.requote_every != 0:
            return
        for symbol in self.symbols:
            self._quote_one(exchange, symbol)

    def _quote_one(self, exchange: Exchange, symbol: str) -> None:
        old_bid, old_ask = self._quote_ids.get(symbol, (None, None))
        if old_bid is not None:
            exchange.cancel_order(old_bid)
        if old_ask is not None:
            exchange.cancel_order(old_ask)

        ref = exchange.last_price.get(symbol) or self._fair_value.get(symbol, 100.0)
        inventory = exchange.positions.get((self.agent_id, symbol), 0)
        skew = -inventory * self.inventory_skew
        bid_price = max(0.01, _round_tick(ref - self.half_spread + skew))
        ask_price = max(bid_price + 0.01, _round_tick(ref + self.half_spread + skew))

        bid = exchange.submit_order(
            symbol, Side.BUY, OrderType.LIMIT, self.quote_size, bid_price,
            TimeInForce.GTC, self.agent_id,
        )
        ask = exchange.submit_order(
            symbol, Side.SELL, OrderType.LIMIT, self.quote_size, ask_price,
            TimeInForce.GTC, self.agent_id,
        )
        self._quote_ids[symbol] = (
            bid.order_id if bid.is_resting else None,
            ask.order_id if ask.is_resting else None,
        )


@dataclass
class NoiseTrader(Agent):
    """Uninformed liquidity: random side, random price near the mid, random
    size, low per-tick activation probability. This is the "background
    noise" order flow every real market has, that a market maker earns the
    spread from."""

    agent_id: str
    symbols: list[str]
    activation_prob: float = 0.25
    max_qty: int = 3
    price_noise: float = 0.30

    def act(self, exchange: Exchange, rng: random.Random, tick: int) -> None:
        for symbol in self.symbols:
            if rng.random() > self.activation_prob:
                continue
            book = exchange.book(symbol)
            mid = book.mid_price() or exchange.last_price.get(symbol) or 100.0
            side = rng.choice([Side.BUY, Side.SELL])
            qty = rng.randint(1, self.max_qty)
            if rng.random() < 0.3:
                # Occasionally cross the spread outright with a market order.
                exchange.submit_order(symbol, side, OrderType.MARKET, qty, None, TimeInForce.IOC, self.agent_id)
            else:
                offset = rng.uniform(-self.price_noise, self.price_noise)
                price = max(0.01, _round_tick(mid + offset))
                exchange.submit_order(symbol, side, OrderType.LIMIT, qty, price, TimeInForce.GTC, self.agent_id)


@dataclass
class MomentumTrader(Agent):
    """Watches the last few trade prices for each symbol and chases the
    trend with a marketable order -- a crude but real momentum/trend-following
    strategy, the kind that amplifies moves rather than dampening them (in
    contrast to the market maker, which leans against inventory)."""

    agent_id: str
    symbols: list[str]
    lookback: int = 5
    threshold: float = 0.4
    qty: int = 4
    activation_prob: float = 0.25

    def act(self, exchange: Exchange, rng: random.Random, tick: int) -> None:
        for symbol in self.symbols:
            if rng.random() > self.activation_prob:
                continue
            recent = [t.price for t in exchange.trade_tape[-self.lookback:] if t.symbol == symbol]
            if len(recent) < 2:
                continue
            move = recent[-1] - recent[0]
            if abs(move) < self.threshold:
                continue
            side = Side.BUY if move > 0 else Side.SELL
            book = exchange.book(symbol)
            best = book.best_ask() if side == Side.BUY else book.best_bid()
            if best is None:
                continue
            # Marketable limit: cross the spread by a couple ticks so it
            # fills like a market order but never trades at an unbounded
            # price if liquidity is thin.
            price = _round_tick(best + 0.05) if side == Side.BUY else _round_tick(best - 0.05)
            price = max(0.01, price)
            exchange.submit_order(symbol, side, OrderType.LIMIT, self.qty, price, TimeInForce.IOC, self.agent_id)


@dataclass
class InformedTrader(Agent):
    """The one agent with a real edge: a precomputed `fundamental` price
    path it alone can see `foresight` ticks into the future. It trades
    toward where the price is *going to be*, which is exactly the mechanism
    by which real informed trading moves prices toward fundamental value
    before public news catches up -- price discovery, not manipulation."""

    agent_id: str
    symbols: list[str]
    fundamental: dict[str, list[float]]
    foresight: int = 20
    aggression: float = 0.5     # fraction of the mispricing to trade on
    max_qty: int = 15
    activation_prob: float = 0.6

    def act(self, exchange: Exchange, rng: random.Random, tick: int) -> None:
        for symbol in self.symbols:
            if rng.random() > self.activation_prob:
                continue
            path = self.fundamental.get(symbol)
            if not path:
                continue
            future_idx = min(tick + self.foresight, len(path) - 1)
            future_value = path[future_idx]
            current = exchange.last_price.get(symbol) or path[min(tick, len(path) - 1)]
            mispricing = future_value - current
            if abs(mispricing) < 0.05:
                continue
            side = Side.BUY if mispricing > 0 else Side.SELL
            qty = min(self.max_qty, max(1, int(abs(mispricing) * self.aggression * 10)))
            book = exchange.book(symbol)
            best = book.best_ask() if side == Side.BUY else book.best_bid()
            ref = best if best is not None else current
            price = _round_tick(ref + 0.10) if side == Side.BUY else _round_tick(ref - 0.10)
            price = max(0.01, price)
            exchange.submit_order(symbol, side, OrderType.LIMIT, qty, price, TimeInForce.IOC, self.agent_id)
