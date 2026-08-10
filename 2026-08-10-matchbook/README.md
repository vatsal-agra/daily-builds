# Matchbook

*A from-scratch limit order book matching engine + multi-agent market simulator.*

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end. See [PLAN.md](./PLAN.md) for the full concept, architecture,
and feature list.

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
