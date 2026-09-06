# Throttle

A from-scratch **TCP transport-protocol and congestion-control simulator**:
a packet-level discrete-event network (bandwidth-limited bottleneck link,
propagation delay, a real drop-tail buffer, loss/reordering) carrying a real
TCP implementation (handshake, sliding-window byte-stream flow control,
out-of-order reassembly, Jacobson/Karels RTT estimation, RTO backoff, and
pluggable Reno/Tahoe/CUBIC congestion control).

> **Status: Phase 3 (adversarial review) complete.** All 4 required
> features are implemented and passing 63 unit/integration tests plus a
> 500-run randomized fuzz sweep (0 crashes, 0 reassembly mismatches). Two
> critical crash/deadlock bugs and one bug in the review tooling itself
> were found and fixed — see `REVIEW.md` for the full account, including
> what was investigated and deliberately *not* changed. See `PLAN.md` for
> architecture. Stretch features and the HTML visualizer are implemented
> but land officially in Phase 4/polish.

## Quick look (implementation in progress, interface may still shift)

```
python3 -m throttle.cli run --bytes 500000 --cc reno
python3 -m throttle.cli experiment rtt-unfairness
python3 -m throttle.cli viz report.html
python3 -m throttle.cli demo
python3 -m pytest
```
