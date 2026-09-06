# Throttle

A from-scratch **TCP transport-protocol and congestion-control simulator**:
a packet-level discrete-event network (bandwidth-limited bottleneck link,
propagation delay, a real drop-tail buffer, loss/reordering) carrying a real
TCP implementation (handshake, sliding-window byte-stream flow control,
out-of-order reassembly, Jacobson/Karels RTT estimation, RTO backoff, and
pluggable Reno/Tahoe/CUBIC congestion control).

> **Status: Phase 5 (verification) complete.** All 4 required features
> plus all 3 stretch features (Tahoe/CUBIC, the HTML visualizer, and RFC
> 2018 SACK) are implemented and green across: 67 pytest unit/integration
> tests, 600+ randomized single- and multi-flow fuzz runs (0 crashes, 0
> reassembly mismatches), and `demo.sh`'s 23-check end-to-end run (every
> feature, every CLI subcommand, invalid-input handling, and a headless-
> Chromium console-error check on the generated report). See `PLAN.md` for
> architecture and `REVIEW.md` for the adversarial-review findings (two
> critical bugs found and fixed, one of them — Reno's slow multi-loss
> recovery without SACK — later turned into the SACK stretch feature that
> fixes it). Full usage docs land in the Phase 6 README.

## Quick look (implementation in progress, interface may still shift)

```
python3 -m throttle.cli run --bytes 500000 --cc reno
python3 -m throttle.cli experiment rtt-unfairness
python3 -m throttle.cli viz report.html
python3 -m throttle.cli demo
python3 -m pytest
```
