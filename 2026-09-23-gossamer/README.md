# Gossamer

A from-scratch Dynamo-style leaderless distributed key-value store: consistent
hashing with virtual nodes, vector clocks for causality, tunable N/R/W quorum
reads/writes, and gossip-based failure detection — with hinted handoff,
Merkle-tree anti-entropy repair, and a live SSE dashboard as stretch goals.

**Status: Phase 1 (plan) complete.** See [PLAN.md](PLAN.md) for the full
concept, architecture, and feature list. Implementation starts next.
