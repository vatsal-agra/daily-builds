# Matchbook

*A from-scratch limit order book matching engine + multi-agent market simulator.*

## What it is

Matchbook is two things built together:

1. **A real price-time-priority limit order book matching engine** —
   the same core algorithm every electronic exchange (NASDAQ, NYSE,
   every crypto venue) runs: orders grouped into price levels, FIFO
   within a level, LIMIT/MARKET/IOC/FOK order types, partial fills,
   cancels, and self-trade prevention. Written entirely from scratch in
   pure Python (stdlib only).
2. **A multi-agent market simulator** — five independently-programmed
   trading strategies (a market maker, a momentum trader, a
   mean-reversion trader, a noise/liquidity trader, and a cross-book
   stat-arb trader) compete for the same book(s) over a seeded,
   deterministic session. No agent is ever told the "true" price — only
   what a real trader could see (the book, the tape, its own
   inventory) — so every trend, spread, and reversal in the output is a
   genuine emergent consequence of the strategies interacting, not
   scripted.

The result renders as a single self-contained, scrubbable HTML replay:
a candlestick chart, a live order-book depth ladder, a scrolling trade
tape, and a P&L leaderboard, with zero server and zero external
dependency.

## How to run it

```bash
# run the full test suite + fuzz harness + demo + SDK example (recommended first run)
./run_tests.sh

# or just generate a fresh session and view it
python3 demo.py --ticks 3000 --seed 42
open output/report.html   # or just open the file in any browser

# throw 60,000 randomized operations at the engine vs. a naive reference matcher
python3 fuzz.py --trials 300 --ops-per-trial 200

# see a third-party strategy plugged into the simulator with zero engine changes
python3 examples/custom_agent_demo.py
```

A sample session is committed at `output/report.html` / `output/session.json`
so you can look at the result without running anything.

## Full feature list

**Required (core):**
1. **Matching engine** (`src/book.py`) — price-time-priority order book;
   LIMIT, MARKET, IOC, FOK order types; partial fills; cancels;
   self-trade prevention; input validation. Guarantees the book never
   crosses and volume is conserved on every trade.
2. **Multi-agent simulator** (`src/simulator.py`, `src/agents.py`) — a
   `MarketMaker` (quotes both sides, skews on inventory, "join and
   improve" pricing), `MomentumTrader`, `MeanReversionTrader`, and
   `NoiseTrader` (passive liquidity most of the time, genuine
   spread-crossing market orders the rest) trading a seeded,
   deterministic multi-tick, multi-instrument session.
3. **Market data pipeline** (`src/marketdata.py`) — trade tape,
   multi-timeframe OHLCV candle aggregation, and periodic order-book
   depth snapshots, all derived live from the real engine's output.
4. **Interactive HTML visualizer** (`src/report_template.py`) — a
   single self-contained file: candlestick chart, live depth ladder,
   trade tape, a legended multi-color P&L leaderboard chart, and a
   scrub/play/step timeline replaying a real recorded session.

**Stretch (both shipped):**
5. **Differential fuzz-testing oracle** (`src/oracle.py`, `fuzz.py`) —
   a deliberately naive, brute-force reference matcher; the fuzz
   harness throws thousands of randomized order/cancel sequences at it
   and the real engine side by side and asserts every trade, best
   bid/ask, and full depth ladder agree exactly. 60,000 operations,
   zero disagreements.
6. **Pluggable strategy SDK** — any class implementing
   `Agent.on_tick(view, rng) -> list[Action]` can be registered with
   the simulator with zero engine changes.
   `examples/custom_agent_demo.py` defines a brand-new
   `LayeredMarketMaker` strategy entirely outside `src/` and runs it
   alongside the built-ins; the shipped demo session also runs
   `StatArbTrader`, a strategy that trades *two* order books at once.

## Verification

```
./run_tests.sh
```

- **47 unit tests** (`tests/`) covering matching-engine invariants
  (never crosses, FIFO priority, all 4 order types, partial fills,
  cancel, self-trade prevention, input validation), every agent's
  decision logic in isolation, candle/depth-snapshot aggregation, and
  full-session simulator behavior (determinism, no self-trades, a
  malformed custom agent can't crash the session).
- **The differential fuzz harness** (60,000 randomized ops, zero
  disagreements with the naive reference matcher).
- **The end-to-end demo** (a full 3000-tick, 2-instrument, 10-agent
  session, checked for zero crossed-book ticks).
- **The pluggable-agent example** (a third-party strategy dropped in
  and run to completion).

See [PLAN.md](./PLAN.md) for the original concept/architecture and
[REVIEW.md](./REVIEW.md) for all 10 adversarial-review findings — real
bugs found and fixed, including a self-trade bug, a crash-on-malformed-
agent-action bug, a script-injection hole in the report generator, and a
`NoiseTrader` that (by construction) could never actually cross the
spread despite its own docstring claiming otherwise.

## Why I chose this today

This repo has 60+ from-scratch builds — compilers, renderers,
transformers, physics engines, crypto, version control, search engines
— but none of them had touched market microstructure. A limit order
book is a small, sharply-specified piece of infrastructure (the same
algorithm every real exchange runs) with correctness invariants that
are easy to state and easy to violate by accident, which makes it a
perfect target for the differential-testing instinct this repo keeps
returning to (a VCS diffed against real git, SAT solutions
independently proof-checked, a JIT checked against `gcc`/`objdump`) —
and stacking a multi-agent simulator on top of a *correct* engine is
where it gets genuinely fun: nothing about the price trends, spreads,
or P&L in the output was authored by hand, all of it falls out of five
independently-programmed strategies reacting only to what a real trader
could see.

## Where a human could take this next

- **Order types real exchanges have that this doesn't**: stop orders,
  pegged orders, iceberg/hidden quantity at the engine level (the
  `LayeredMarketMaker` example fakes this at the agent level today),
  post-only, good-till-date.
- **Multi-threaded / async matching** with a proper sequencer, so
  agents could run as real concurrent processes submitting over a
  socket instead of a single-threaded tick loop — closer to how a real
  venue's gateway/matching-engine split works.
- **A learned agent**: replace one strategy with a small RL policy
  trained against the existing agents as its environment, and see if it
  discovers a strategy that beats the hand-written ones.
- **Persist the book to disk** (write-ahead log + snapshot, the same
  pattern this repo's LSM-tree and B+tree projects used) so a session
  can crash and resume without losing state.
- **A FIX-like text wire protocol** in front of `submit()`/`cancel()`,
  so an external process (or a second language entirely) could drive
  the same engine over a socket instead of calling Python directly.
- **Latency/queue-position modeling**: right now every agent's action
  within a tick is applied instantly; a more realistic model would give
  each agent's message a simulated network+processing delay, which
  would make queue-position games (who gets there first at a price)
  a real strategic dimension instead of just simulator tick order.
