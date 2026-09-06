# Throttle

A from-scratch **TCP transport-protocol and congestion-control simulator**:
a packet-level discrete-event network (bandwidth-limited bottleneck link,
propagation delay, a real drop-tail buffer, loss/reordering) carrying a real
TCP implementation (handshake, sliding-window byte-stream flow control,
out-of-order reassembly, Jacobson/Karels RTT estimation, RTO backoff, and
pluggable Reno/Tahoe/CUBIC congestion control).

> **Status: Phase 1 (plan) complete.** See `PLAN.md` for the full
> architecture and feature list. Implementation in progress — this file
> will be replaced with real usage instructions as each phase lands.
