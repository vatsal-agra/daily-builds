# Undertow

*Status: Phase 2 — core build complete. All 4 required features work
end-to-end; both stretch features are also implemented. 24/24 tests green.*

A from-scratch, packet-level network simulator implementing real TCP
congestion-control algorithms (Reno, CUBIC, and a BBR-lite) to reproduce
textbook-verifiable phenomena — AIMD fairness convergence, RTT unfairness,
and bufferbloat — as automated, assertion-checked experiments rather than
hand-waved charts.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.

## Try it

```
python3 -m pytest tests/ -q
python3 -m src.cli single --algo reno --duration 20
python3 -m src.cli fairness --algo reno --duration 40
python3 -m src.cli rtt-unfairness --algo cubic --duration 60
python3 -m src.cli bufferbloat --algo reno --duration 30 --red
python3 -m src.cli bbr-vs-loss --algo cubic --duration 30
```

## Results so far (real simulator output, not illustrative)

- Single Reno/CUBIC/BBR flow on a 2 Mbps link: 94–99.7% utilization.
  BBR gets there with **zero** packet drops; Reno/CUBIC need loss to find
  the link's capacity (that's the whole point of loss-based control).
- Two identical-RTT Reno flows: converge to a fair split (Jain's index
  ≈0.99 over the full run).
- Reno, RTT ratio 4:1: short-RTT flow gets a pooled ~1.1-1.5x share over
  the long-RTT flow (RTT unfairness, reproduced). CUBIC on the identical
  topology: pooled ratio ≈1.0–1.1 — measurably fairer, as RFC 8312 intends.
- Drop-tail with a deep queue: a latency-sensitive flow's RTT balloons to
  **26x** its base RTT under a competing bulk flow (bufferbloat). RED on
  the identical scenario cuts that to ~11x while keeping >98% utilization.
- BBR vs CUBIC on the same generously-buffered bottleneck, both near 100%
  utilization: BBR holds a mean queue of ~6 packets; CUBIC fills the
  buffer to ~100+ packets. This is BBR's entire reason for existing,
  reproduced end-to-end.

Remaining phases (adversarial review, polish, verification, ship) still to
come — this README will be updated after each one.
