"""Wires a population of independent agents to a live `Exchange` and drives
a deterministic, seeded discrete-event trading session.

Nothing about the resulting price path is scripted: each tick, every agent
looks only at public market state (plus, for `InformedTrader` alone, a
private look-ahead into a precomputed fundamental-value path) and decides
independently whether to act. The emergent trade tape is a genuine
side-effect of those decisions colliding in the order book, not a canned
sequence -- but because a single `random.Random(seed)` drives every random
choice made by every agent, and agents act in a fixed order each tick, the
exact same seed reproduces the exact same session byte-for-byte.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .agents import Agent, InformedTrader, MarketMaker, MomentumTrader, NoiseTrader
from .engine import Exchange
from .risk import RiskLimits


@dataclass
class SimulationConfig:
    symbols: list[str] = field(default_factory=lambda: ["ACME"])
    n_ticks: int = 500
    seed: int = 42
    start_price: float = 100.0
    fundamental_vol: float = 0.08
    n_market_makers: int = 2
    n_noise_traders: int = 6
    n_momentum_traders: int = 3
    n_informed_traders: int = 1
    informed_foresight: int = 20
    journal_path: str | None = None
    risk_limits: RiskLimits | None = None
    self_trade_prevention: bool = True


def generate_fundamental(symbols: list[str], n_ticks: int, start_price: float, vol: float, rng: random.Random) -> dict[str, list[float]]:
    """A simple bounded random walk per symbol: the "true" value process that
    only `InformedTrader` gets to see ahead of time. Reflected at a small
    floor so it never wanders to (or through) zero."""
    paths: dict[str, list[float]] = {}
    for symbol in symbols:
        price = start_price
        path = [price]
        for _ in range(n_ticks + 64):  # pad so foresight look-ahead never runs off the end
            price += rng.gauss(0, vol)
            price = max(1.0, price)
            path.append(price)
        paths[symbol] = path
    return paths


def build_agents(config: SimulationConfig, fundamental: dict[str, list[float]]) -> list[Agent]:
    agents: list[Agent] = []
    for i in range(config.n_market_makers):
        mm = MarketMaker(agent_id=f"MM{i}", symbols=config.symbols)
        for s in config.symbols:
            mm.set_initial_fair_value(s, config.start_price)
        agents.append(mm)
    for i in range(config.n_noise_traders):
        agents.append(NoiseTrader(agent_id=f"NOISE{i}", symbols=config.symbols))
    for i in range(config.n_momentum_traders):
        agents.append(MomentumTrader(agent_id=f"MOM{i}", symbols=config.symbols))
    for i in range(config.n_informed_traders):
        agents.append(
            InformedTrader(
                agent_id=f"INFORMED{i}",
                symbols=config.symbols,
                fundamental=fundamental,
                foresight=config.informed_foresight,
            )
        )
    return agents


class Simulator:
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.rng = random.Random(config.seed)
        self.fundamental = generate_fundamental(
            config.symbols, config.n_ticks, config.start_price, config.fundamental_vol, self.rng
        )
        self.agents = build_agents(config, self.fundamental)
        self.exchange = Exchange(
            symbols=config.symbols,
            journal_path=config.journal_path,
            risk_limits=config.risk_limits,
            self_trade_prevention=config.self_trade_prevention,
        )
        self.ticks_run = 0
        self.history: list[dict] = []

    def step(self, record_history: bool = True) -> None:
        for agent in self.agents:
            agent.act(self.exchange, self.rng, self.ticks_run)
        if record_history:
            self.history.append(
                {
                    "tick": self.ticks_run,
                    # Watermark on the order-arrival sequence axis (NOT the
                    # same scale as `tick` -- many orders are submitted per
                    # tick), used to filter "trades/candles that have
                    # happened as of this point in the replay."
                    "seq": self.exchange.order_seq_counter,
                    "depths": {
                        s: self.exchange.book(s).depth(n=10) for s in self.config.symbols
                    },
                }
            )
        self.ticks_run += 1

    def run(self, n_ticks: int | None = None, record_history: bool = True) -> Exchange:
        total = n_ticks if n_ticks is not None else self.config.n_ticks
        for _ in range(total):
            self.step(record_history=record_history)
        return self.exchange

    def close(self) -> None:
        self.exchange.close()
