# Matchbook

A from-scratch exchange matching engine and market simulator: a real
price-time-priority limit order book, a durable event-sourced journal with
crash recovery, a population of independent trading agents that produce
emergent price action with nothing scripted, and an interactive HTML
replay of a finished session — no server required to view it.

## What it is

Every stock/crypto/futures exchange runs on the same small, brutal core: a
**limit order book** that matches buyers and sellers by price-time
priority. Matchbook implements that core for real — not a simplified toy —
and then wires it into a **living market**: a market maker quoting both
sides for the spread, momentum traders chasing trends, noise traders
providing random flow, and one informed trader secretly trading on a
signal the rest of the market has to discover the hard way. Nobody scripts
the price path; it emerges from independent agents' orders colliding in
the same book, the same way real market microstructure does.

## How to run it

```bash
cd 2026-09-04-matchbook

# Run the full end-to-end verification (unit tests + 16 feature checks)
./demo.sh

# Or drive it by hand:
python3 -m matchbook.cli demo                      # tour of every feature
python3 -m matchbook.cli run --ticks 500            # simulate, print a JSON summary
python3 -m matchbook.cli viz --out session.html     # render an interactive replay
open session.html                                   # (or just double-click it — no server needed)
python3 -m matchbook.cli crash-demo                 # prove journal-only crash recovery
python3 -m matchbook.cli replay some.journal         # rebuild state from a journal alone

python3 -m unittest discover -s tests               # 101 unit/property tests
```

Every subcommand takes `--symbols`, `--ticks`, `--seed`, and a full set of
market/risk knobs — run `python3 -m matchbook.cli <subcommand> --help` for
the complete list.

## Full feature list

**Required (all 4 implemented and demonstrably working end-to-end):**

1. **Price-time-priority matching engine** (`matchbook/book.py`) — limit,
   market, IOC (immediate-or-cancel), and FOK (fill-or-kill, atomic — all
   or nothing with zero book effect otherwise) orders; partial fills;
   cancel; cancel/replace. Verified by property tests (price-time priority
   and share conservation) fuzzed over hundreds of random order sequences,
   not just fixed examples.
2. **Event-sourced journal with crash recovery** (`matchbook/journal.py`,
   `matchbook/engine.py`) — every accepted order/cancel/modify is appended
   to a CRC-32-checked, fsynced, append-only log *before* it mutates
   in-memory state. `Exchange.replay()` rebuilds exact state from the log
   alone, byte-for-byte identical to what was live — demonstrated by
   literally abandoning a live `Exchange` mid-session (no clean shutdown)
   and reconstructing it purely from disk.
3. **Multi-agent market simulation** (`matchbook/agents.py`,
   `matchbook/simulator.py`) — a `MarketMaker` (inventory-skewed quoting on
   both sides), `NoiseTrader`s (random uninformed flow), `MomentumTrader`s
   (trend-chasing), and an `InformedTrader` (a private look-ahead into a
   fundamental-value path the rest of the market can't see) all submit real
   orders to the same live book over a seeded, fully deterministic session.
   Same seed → byte-identical trade tape, every time.
4. **Interactive HTML visualizer** (`matchbook/viz.py`) — one self-contained
   file (no server, no external dependencies) with a scrubbable OHLCV
   candlestick chart, a live order-book depth ladder, a scrolling trade
   tape, and an agent P&L leaderboard, all reconstructed from a finished
   session's real journal and trade tape.

**Stretch (2 implemented, both load-bearing — the simulation needed them
to be realistic, not bolted on afterward):**

5. **Risk engine** (`matchbook/risk.py`) — per-agent position limits,
   self-trade prevention (an agent's own resting order is cancelled rather
   than matched against its own incoming order), and fat-finger price
   collars, enforced pre-trade with every rejection recorded and reasoned.
6. **Multi-symbol exchange with cross-symbol portfolios** — `Exchange` runs
   several independent order books at once, with each agent's
   position/cash/mark-to-market P&L tracked across every symbol
   simultaneously.

## Why I chose this today

This repo has built a lot of "from scratch" systems — languages, VCS
implementations, crypto, renderers, search engines, SAT solvers, nine
separate Transformers — but never **market microstructure**: the plumbing
that decides who gets to trade at what price under contention. It's a
compact, precisely-specified algorithm with an unusually rich set of
*mechanically checkable* correctness invariants (share conservation,
price-time priority, FOK atomicity, replay-equals-live), and it produces
something genuinely interesting to look at — real-looking candlestick
price action and market-maker adverse selection — that emerges from
independent agents rather than being hand-tuned to look nice. It also let
me build something with genuine "hard invariant" oracles the way past SAT
solvers and VCS implementations did (a differential proof-checker, a real
`git` oracle), but in a domain — exchanges — that's both economically
central and that I hadn't seen this repo touch.

## Adversarial review

Phase 3 found and fixed 8 real issues, the worst a critical silent-order-
loss bug in `OrderBook.modify()` — full writeup in [`REVIEW.md`](./REVIEW.md).

## Where a human could take this next

- **Real limit-order-book depth charts and Level 2 market data feeds** —
  the `depth()` snapshot already exists; a WebSocket/SSE feed off it would
  turn this into something a real trading UI could consume live.
- **More realistic agents**: a proper Avellaneda-Stoikov market maker with
  volatility-aware spread widening, a mean-reverting stat-arb agent, or
  agents with actual latency (network delay between decision and order
  arrival) instead of the current "acts once per discrete tick" model.
- **Auction mechanisms**: opening/closing call auctions (uncrossing a batch
  of orders at a single clearing price) alongside the current continuous
  double auction — real exchanges run both.
- **Order book snapshots + incremental deltas** as a wire format, so the
  journal could double as a real market-data replay/backtesting format for
  external strategies, not just this repo's own agents.
- **A real accompanying options/futures layer** priced off the underlying
  spot book, since the risk engine and multi-symbol plumbing are already
  in place to support it.
- **Persistent order books across restarts** (the journal already supports
  this in principle — `Exchange.replay()` at startup instead of only after
  a simulated crash — this just isn't wired into a long-running daemon
  mode yet).
