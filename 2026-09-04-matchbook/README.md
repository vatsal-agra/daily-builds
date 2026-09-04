# Matchbook

> Status: **Phase 3 — Adversarial review complete.** All 4 required features
> work end-to-end; 7 real issues found by hostile testing (including a
> critical silent-order-loss bug) are fixed and regression-tested. See
> [`REVIEW.md`](./REVIEW.md). Stretch polish and final verification still
> to come.

A from-scratch exchange matching engine: a real price-time-priority limit
order book, an event-sourced journal with crash recovery, a multi-agent
market simulator that produces emergent price action, and an interactive
HTML visualizer of a finished trading session.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.

## Quick start

```bash
cd 2026-09-04-matchbook
python3 -m matchbook.cli demo            # exercises every feature end-to-end
python3 -m matchbook.cli run --ticks 500 # run a simulation, print a summary
python3 -m matchbook.cli viz --out session.html   # render an interactive replay
python3 -m matchbook.cli crash-demo      # prove journal-only crash recovery
python3 -m unittest discover -s tests    # run the test suite
```

## What's implemented so far

1. **Matching engine** (`matchbook/book.py`) — price-time priority, limit /
   market / IOC / FOK orders, partial fills, cancel, cancel-replace.
2. **Event-sourced journal** (`matchbook/journal.py`, `matchbook/engine.py`)
   — every command is durably logged (CRC-checked, fsynced) before it
   mutates state; `Exchange.replay()` rebuilds exact state from the log
   alone.
3. **Multi-agent market simulation** (`matchbook/agents.py`,
   `matchbook/simulator.py`) — market makers, noise traders, momentum
   traders, and an informed trader with a private signal, all generating
   real emergent order flow.
4. **Interactive HTML visualizer** (`matchbook/viz.py`) — scrubbable replay
   with a candlestick chart, depth ladder, and trade tape, no server
   required.

Stretch features also live and demonstrated by `demo`:

5. **Risk engine** (`matchbook/risk.py`) — position limits, self-trade
   prevention, fat-finger collars, enforced pre-trade.
6. **Multi-symbol exchange** — `Exchange` runs several independent order
   books with cross-symbol per-agent P&L.

Remaining work: further polish (Phase 4), a full verification pass
(Phase 5), and final documentation (Phase 6).
