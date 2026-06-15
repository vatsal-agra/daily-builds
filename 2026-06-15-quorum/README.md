# Quorum

A deterministic **Raft consensus simulator** with an adversarial network, fault
injection, and machine-checked safety invariants. Built as a daily build on
2026-06-15.

> Status: **Phase 1 — Plan complete.** See [PLAN.md](./PLAN.md) for the full
> concept, architecture, and feature list. README will be filled out as the
> build progresses.

## What it will be
Spin up a cluster of Raft nodes inside a seeded discrete-event network, drive
time forward, inject crashes / partitions / message loss, and prove that Raft's
safety properties hold no matter how hostile the network gets — all fully
deterministic and replayable.

See [PLAN.md](./PLAN.md) for details.
