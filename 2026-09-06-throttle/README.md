# Throttle

A from-scratch **TCP transport-protocol and congestion-control simulator**:
a packet-level discrete-event network (bandwidth-limited bottleneck link,
propagation delay, a real drop-tail buffer, loss/reordering) carrying a real
TCP implementation (handshake, sliding-window byte-stream flow control,
out-of-order reassembly, Jacobson/Karels RTT estimation, RTO backoff, and
pluggable Reno/Tahoe/CUBIC congestion control).

> **Status: Phase 2 (core build) complete.** All 4 required features are
> implemented and passing 59 unit/integration tests, plus 6 canned
> experiments that each check a real, falsifiable TCP prediction (not
> eyeballed). See `PLAN.md` for architecture. `REVIEW.md` and the stretch
> features/visualizer land in later phases.

## Quick look (implementation in progress, interface may still shift)

```
python3 -m throttle.cli run --bytes 500000 --cc reno
python3 -m throttle.cli experiment rtt-unfairness
python3 -m throttle.cli viz report.html
python3 -m throttle.cli demo
python3 -m pytest
```
