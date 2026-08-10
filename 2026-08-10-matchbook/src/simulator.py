"""Drives a deterministic, seeded, multi-agent, multi-instrument trading
session on top of the real matching engine.

Determinism matters here the way it mattered for Raft-Sim's discrete
event scheduler earlier in this repo: same seed -> byte-identical
session, so any interesting or buggy emergent behavior is 100%
reproducible, not a one-off fluke of the RNG.
"""
import random
from collections import defaultdict

from order import Side, OrderType
from book import OrderBook
from agents import BookView
from marketdata import DepthRecorder


class MarketSimulator:
    def __init__(self, symbols, seed=42):
        self.symbols = list(symbols)
        self.books = {sym: OrderBook(sym) for sym in self.symbols}
        self.rng = random.Random(seed)
        self.agents = []  # list of (agent, primary_symbol)
        self.cash = defaultdict(int)
        self.inventory = defaultdict(lambda: defaultdict(int))
        self.trade_tape = defaultdict(list)
        self.depth_recorders = {sym: DepthRecorder() for sym in self.symbols}
        self.pnl_history = defaultdict(list)  # owner -> [(t, pnl), ...]
        self.pnl_every = 5
        self.t = 0

    def register(self, agent, primary_symbol):
        assert primary_symbol in self.books, f"unknown symbol {primary_symbol!r}"
        self.agents.append((agent, primary_symbol))

    def seed_liquidity(self, symbol, mid, rung_ticks=15, levels=6, qty=40):
        """Places static resting orders owned by 'SEED' so the book isn't
        empty at t=0. SEED never trades again after this — it's not an
        agent, just bootstrap liquidity, exactly like an exchange opening
        auction leaves a residual book."""
        book = self.books[symbol]
        for i in range(levels):
            book.submit(Side.BUY, OrderType.LIMIT, qty, price=max(1, mid - rung_ticks * (i + 1)), owner="SEED")
            book.submit(Side.SELL, OrderType.LIMIT, qty, price=mid + rung_ticks * (i + 1), owner="SEED")

    def _make_view(self, symbol, owner, window=40):
        book = self.books[symbol]
        recent = self.trade_tape[symbol][-window:]
        return BookView(
            symbol=symbol,
            tick=self.t,
            best_bid=book.best_bid(),
            best_ask=book.best_ask(),
            depth=book.depth(8),
            recent_trades=recent,
            my_open_orders=book.open_orders_of(owner),
            my_inventory=self.inventory[owner][symbol],
            my_cash=self.cash[owner],
        )

    def step(self):
        self.t += 1
        for book in self.books.values():
            book.tick(self.t)

        order = list(self.agents)
        self.rng.shuffle(order)  # no systematic tick-priority bias
        for agent, primary_symbol in order:
            view = self._make_view(primary_symbol, agent.name)
            if len(self.symbols) > 1:
                other_syms = [s for s in self.symbols if s != primary_symbol]
                if other_syms:
                    view.other_symbol_view = self._make_view(other_syms[0], agent.name)
            for action in agent.on_tick(view, self.rng):
                self._apply_action(agent, action, primary_symbol)

        for sym, book in self.books.items():
            self.depth_recorders[sym].maybe_record(book, self.t)

        if self.t % self.pnl_every == 0:
            for agent, _ in self.agents:
                self.pnl_history[agent.name].append((self.t, self.mark_to_market(agent.name)))

    def _apply_action(self, agent, action, primary_symbol):
        symbol = action.symbol or primary_symbol
        book = self.books[symbol]
        if action.kind == "cancel":
            book.cancel(action.order_id)
            return
        _resting, trades = book.submit(
            action.side, action.otype, action.qty, price=action.price, owner=agent.name, ts=self.t,
        )
        if trades:
            self.trade_tape[symbol].extend(trades)
            for tr in trades:
                self._settle(symbol, tr)

    def _settle(self, symbol, trade):
        maker_side = trade.aggressor_side.opposite
        self._apply_fill(symbol, trade.maker_owner, maker_side, trade.qty, trade.price)
        self._apply_fill(symbol, trade.taker_owner, trade.aggressor_side, trade.qty, trade.price)

    def _apply_fill(self, symbol, owner, side, qty, price):
        sign = 1 if side is Side.BUY else -1
        self.inventory[owner][symbol] += sign * qty
        self.cash[owner] -= sign * qty * price

    def run(self, n_ticks):
        for _ in range(n_ticks):
            self.step()

    def mark_to_market(self, owner):
        """Realized + unrealized P&L in ticks: cash plus current inventory
        marked at each symbol's last trade price (or book mid if no trade
        occurred yet on that symbol)."""
        pnl = self.cash[owner]
        for symbol, qty in self.inventory[owner].items():
            if qty == 0:
                continue
            tape = self.trade_tape[symbol]
            mark = tape[-1].price if tape else self.books[symbol].mid_price()
            if mark is None:
                continue
            pnl += qty * mark
        return pnl

    def leaderboard(self):
        rows = [(agent.name, self.mark_to_market(agent.name), dict(self.inventory[agent.name]))
                for agent, _ in self.agents]
        rows.sort(key=lambda r: r[1], reverse=True)
        return rows
