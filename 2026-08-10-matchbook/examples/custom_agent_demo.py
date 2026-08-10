#!/usr/bin/env python3
"""Demonstrates the pluggable Agent SDK (stretch feature #6): a
brand-new trading strategy, written entirely in this file with zero
changes to `src/agents.py`, dropped into a real simulator session
alongside the built-in strategies.

`LayeredMarketMaker` is materially different from the built-in
`MarketMaker` — instead of quoting one price level per side, it lays
down a whole ladder of resting orders at several price increments, a
real market-making technique ("iceberg"/layered quoting) that spreads
fill risk across multiple prices instead of concentrating it at the
touch. Nothing about the engine or simulator needed to know this
strategy exists ahead of time; it only needs the public `Agent` /
`Action` / `BookView` contract from `src/agents.py`.

Run: python3 examples/custom_agent_demo.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator import MarketSimulator
from agents import Agent, Action, MarketMaker, NoiseTrader, MomentumTrader
from order import Side, OrderType


class LayeredMarketMaker(Agent):
    """A third-party strategy: quotes `n_levels` resting orders on each
    side, spaced `step` ticks apart, instead of a single top-of-book
    quote. Demonstrates that a custom Agent can freely manage many of
    its own resting orders across a tick — the SDK contract only asks
    for a list of Actions back, nothing about their shape or count."""

    def __init__(self, name, n_levels=4, step=6, qty=8, min_edge=5):
        super().__init__(name)
        self.n_levels = n_levels
        self.step = step
        self.qty = qty
        self.min_edge = min_edge

    def on_tick(self, view, rng):
        actions = [Action("cancel", order_id=o.id) for o in view.my_open_orders]

        if view.recent_trades:
            fair = view.recent_trades[-1].price
        elif view.best_bid is not None and view.best_ask is not None:
            fair = (view.best_bid + view.best_ask) // 2
        else:
            return actions

        for level in range(self.n_levels):
            bid_price = max(1, fair - self.min_edge - level * self.step)
            ask_price = fair + self.min_edge + level * self.step
            actions.append(Action("place", side=Side.BUY, otype=OrderType.LIMIT,
                                   qty=self.qty, price=bid_price))
            actions.append(Action("place", side=Side.SELL, otype=OrderType.LIMIT,
                                   qty=self.qty, price=ask_price))
        return actions


def main():
    sim = MarketSimulator(["DEMO"], seed=7)
    sim.seed_liquidity("DEMO", mid=5000)
    sim.register(NoiseTrader("noise.1", mid_guess=5000), "DEMO")
    sim.register(NoiseTrader("noise.2", mid_guess=5000, place_prob=0.4), "DEMO")
    sim.register(MomentumTrader("momentum"), "DEMO")
    sim.register(MarketMaker("builtin.mm"), "DEMO")          # a stock built-in strategy...
    sim.register(LayeredMarketMaker("custom.layered"), "DEMO")  # ...alongside a brand-new one

    sim.run(1500)

    book = sim.books["DEMO"]
    print(f"ticks simulated: {sim.t}")
    print(f"trades: {len(sim.trade_tape['DEMO'])}  "
          f"best_bid={book.best_bid()}  best_ask={book.best_ask()}  "
          f"crossed={book.best_bid() is not None and book.best_ask() is not None and book.best_bid() >= book.best_ask()}")
    print("\nleaderboard:")
    for name, pnl, inv in sim.leaderboard():
        marker = "  <- custom third-party strategy" if name == "custom.layered" else ""
        print(f"  {name:16s} {pnl:8d}  {inv}{marker}")


if __name__ == "__main__":
    main()
