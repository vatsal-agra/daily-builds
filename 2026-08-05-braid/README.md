# Braid

*Status: Phase 3 (adversarial review) complete — 6 real bugs found and
fixed (2 of them serious CRDT correctness bugs no prior automated test
had caught), see [REVIEW.md](./REVIEW.md). Build in progress; see
[PLAN.md](./PLAN.md) for the full concept and architecture.*

A real-time collaborative text editor whose consistency guarantee comes
from a from-scratch **CRDT** (Conflict-free Replicated Data Type) — no
OT, no central sequencer, no CRDT library.

## Try it now

```bash
cd 2026-08-05-braid
python3 cli.py serve            # then open http://localhost:8420/ in 2+ tabs
python3 cli.py scenario         # headless offline/reconnect walkthrough
python3 cli.py sweep --count 200  # Strong Eventual Consistency proof, 200 seeds
```

## What's built so far

- **`crdt/rga.py` / `static/rga.js`** — the from-scratch Replicated
  Growable Array CRDT engine, hand-ported 1:1 to both Python (server/CLI)
  and JavaScript (every browser tab runs its own real replica).
- **`crdt/network.py`** — a deterministic, seeded adversarial network
  simulator (latency/reorder/duplication/loss/partition) plus anti-entropy
  gossip, driving a convergence proof (`cli.py sweep`).
- **`server.py` + `static/*`** — a real-time multi-tab collaborative
  editor: local-first editing, live sync over Server-Sent Events, presence
  with live peer cursors, a "go offline" chaos toggle, and CRDT-aware
  undo/redo.
- **`cli.py`** — headless simulation, convergence sweeps, and a narrated
  offline/reconnect scenario, no browser required.

Full usage, feature list, and design notes will land in this README as
later phases (adversarial review, polish, verification, ship) complete.
