# Matchbook

*A from-scratch limit order book matching engine + multi-agent market simulator.*

**Status: Phase 5 (verification) complete — 47/47 tests green.** All 4
required features plus both stretch features are done and tested. See
[PLAN.md](./PLAN.md) for the concept/architecture/feature list and
[REVIEW.md](./REVIEW.md) for all 10 adversarial-review findings
(9 from Phase 3's hostile self-review, 1 more caught while writing
Phase 5's tests — a `NoiseTrader` that, by construction, could never
actually cross the spread).

## Verification

```
./run_tests.sh
```

Runs, and requires all-green:
- **47 unit tests** (`tests/`) — matching-engine invariants (never
  crosses, FIFO price-time priority, partial fills, all 4 order types,
  cancel, self-trade prevention, input validation), every agent's
  decision logic in isolation, candle/depth-snapshot aggregation,
  full-session simulator behavior (determinism, no self-trades, a
  malformed custom agent can't crash the session), and the report
  generator (valid HTML, script-injection escaping, recoverable JSON).
- **The differential fuzz harness** — 60,000 randomized operations,
  real engine vs. naive reference matcher, zero disagreements.
- **The end-to-end demo** — a full 3000-tick, 2-instrument, 10-agent
  session, checked for zero crossed-book ticks.
- **The pluggable-agent example** — a third-party strategy dropped in
  with zero engine changes, run to completion.

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
