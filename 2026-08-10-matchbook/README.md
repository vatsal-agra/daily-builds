# Matchbook

*A from-scratch limit order book matching engine + multi-agent market simulator.*

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
plus both stretch features are done: a differential fuzz-testing oracle
(`fuzz.py`/`src/oracle.py`) and a demonstrated pluggable Agent SDK
(`examples/custom_agent_demo.py`, plus the built-in cross-book stat-arb
agent). See [PLAN.md](./PLAN.md) for the concept/architecture/feature
list and [REVIEW.md](./REVIEW.md) for the adversarial-review findings.

## Stretch features

- **Differential fuzz-testing oracle** — `src/oracle.py` is a
  deliberately naive, brute-force reference matcher; `fuzz.py` throws
  thousands of randomized order/cancel sequences at it and the real
  engine side by side and asserts every trade, best bid/ask, and full
  depth ladder match exactly. `python3 fuzz.py --trials 300` runs 60,000
  randomized operations with zero disagreements.
- **Pluggable strategy SDK** — any class implementing `Agent.on_tick(view, rng) -> list[Action]`
  (from `src/agents.py`) can be registered with the simulator, with zero
  engine changes. `examples/custom_agent_demo.py` defines a brand-new
  `LayeredMarketMaker` strategy entirely outside `src/` and runs it
  alongside the built-ins. The shipped demo session also runs
  `StatArbTrader`, a strategy that trades *two* order books at once.

## Quick look

```
python3 demo.py --ticks 3000 --seed 42
open output/report.html   # (or just open the file in a browser)
```

This runs a full deterministic session — a price-time-priority matching
engine, two order books (`ACME`, `GLBX`), and 10 trading agents (market
makers, noise/liquidity traders, momentum traders, mean-reversion
traders, and a cross-book stat-arb trader) — and writes a self-contained,
scrubbable HTML replay: candlestick chart, live order-book depth ladder,
trade tape, and a P&L leaderboard. A sample run is committed at
`output/report.html`.

Build in progress — this README will grow with the full feature list,
adversarial-review findings, and a "where a human could take this next"
section as later phases land.
