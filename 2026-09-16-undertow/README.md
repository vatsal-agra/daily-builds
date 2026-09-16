# Undertow

A TCP-shaped reliable transport protocol, built from scratch on raw UDP
sockets: real packet checksums, a 3-way handshake, wraparound-safe sequence
numbers, Jacobson/Karels RTO estimation with Karn's algorithm, selective
ACKs, and genuine Reno-style congestion control (slow start → congestion
avoidance → fast retransmit → fast recovery).

**Status: Phase 1 (plan) complete.** See [PLAN.md](PLAN.md) for the full
architecture and feature list. Implementation starts next phase — this
README will be replaced with real usage instructions once the core protocol
exists.
