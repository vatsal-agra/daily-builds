# Matchbook — Plan

## Concept

A **limit order book matching engine** and a **multi-agent market
simulator** built from scratch, in pure Python (stdlib only — no pandas,
no numpy, no exchange/trading library of any kind).

Every prior daily build that touched "markets" or "finance" touched
neither — this repo has 60+ from-scratch builds (compilers, renderers,
transformers, physics engines, crypto, VCS, search engines...) but never
market microstructure. This is a genuinely new domain: instead of
simulating physics or language, we simulate an *economy* — independent
trading agents with different strategies competing for the same book,
producing emergent price action nobody scripted.

## Why it's interesting

A limit order book is a small, precise piece of infrastructure (the same
price-time-priority matching algorithm that runs NASDAQ, NYSE, and every
crypto exchange) with sharp correctness invariants that are easy to state
and easy to violate accidentally: the book must never cross (best bid <
best ask), volume must be conserved across every match, and orders at the
same price must fill in the order they arrived. That makes it an ideal
target for **differential testing** against a deliberately naive
brute-force reference matcher — the same "don't trust it just because it
looks plausible, prove it" instinct behind this repo's SAT proof
checkers, VCS-vs-real-git diffing, and gradient-checked autodiff engines.

On top of a correct engine, a multi-agent simulator is where it gets
fun: a market maker, a momentum trader, a mean-reversion trader, and a
noise trader all act on nothing but the visible book and trade tape (no
agent is handed the "true" fair value) — yet realistic-looking price
trends, spreads, and mean-reversion emerge purely from the interaction of
simple, independently-programmed strategies. Nothing in the output is
hand-authored: every price, trade, and candle comes out of running the
engine.

## Architecture

```
matchbook/
  src/
    order.py       — Order/Trade dataclasses, Side/OrderType enums
    book.py         — OrderBook: price-time-priority matching engine
    agents.py        — Agent base class + 5 concrete strategies
    simulator.py      — MarketSimulator: seeded, deterministic multi-agent
                        multi-instrument session driver
    marketdata.py     — trade tape -> OHLCV candles (multi-timeframe) +
                        depth-ladder snapshots, all derived, none stored twice
    oracle.py          — naive O(n) reference matcher, used only to
                        differentially fuzz-test book.py
  tests/               — unit + invariant + differential tests (unittest)
  fuzz.py              — randomized differential stress harness (stretch)
  demo.py               — runs a full simulated session end-to-end,
                          writes output/session.json + output/report.html
  report_template.py    — builds the self-contained interactive HTML viewer
  run_tests.sh
```

Data flow: `simulator.py` drives ticks. Each tick, every agent sees a
read-only `BookView` (best bid/ask, depth, own open orders, trade tape
history) and returns order actions, which `book.py` matches immediately.
Trades and periodic depth snapshots stream into `marketdata.py`, which
aggregates them into candles. `demo.py` runs a full session and hands the
recorded session to `report_template.py`, which embeds it as JSON inside
a single self-contained HTML file — a candlestick chart, live depth
ladder, trade tape, and P&L leaderboard, scrubbable across the whole
session, in the same "server-free single-file interactive viewer"
pattern this repo has used for its physics playgrounds and evolution
replays.

## Feature list

### Required (core, must work end-to-end)

1. **Matching engine** — price-time-priority limit order book with
   LIMIT, MARKET, IOC (immediate-or-cancel), and FOK (fill-or-kill)
   orders, partial fills, and cancels. Maintains the invariant that the
   book never crosses and that filled volume is conserved on both sides
   of every trade.
2. **Multi-agent simulator** — four independently-programmed strategies
   (market maker, momentum, mean-reversion, noise/liquidity trader)
   trading against a shared book over a seeded, deterministic multi-tick
   session, with no agent given the "true" price — only what the book
   and tape show.
3. **Market data pipeline** — trade tape, multi-timeframe OHLCV
   candlestick aggregation, and periodic order-book depth snapshots, all
   computed live from the actual matching engine's output (nothing
   canned).
4. **Interactive HTML visualizer** — a single self-contained HTML file
   (candlestick chart, live depth ladder, scrolling trade tape, P&L
   leaderboard, time-scrubber/playback) that replays a real recorded
   session with zero server and zero external dependency.

### Stretch (2+, at least 1 implemented)

5. **Differential fuzz-testing oracle** — a deliberately naive O(n)
   reference matcher plus a randomized fuzz harness that throws thousands
   of random order sequences at both implementations and asserts
   identical resulting trades/book state, proving matching correctness
   independent of "it looks right."
6. **Pluggable strategy SDK + stat-arb demo** — a documented `Agent`
   interface any third-party strategy can implement, demonstrated with a
   two-instrument statistical-arbitrage agent that trades the spread
   between a pair of correlated order books.

## Non-goals

No real money, no real exchange connectivity, no persistence beyond a
single session's JSON recording. This is a simulation and teaching tool,
not a trading system.
