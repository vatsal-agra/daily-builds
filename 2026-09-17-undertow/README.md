# Undertow

*Status: Phase 1 — planning complete, build starting.*

A from-scratch, packet-level network simulator implementing real TCP
congestion-control algorithms (Reno, CUBIC, and a BBR-lite) to reproduce
textbook-verifiable phenomena — AIMD fairness convergence, RTT unfairness,
and bufferbloat — as automated, assertion-checked experiments rather than
hand-waved charts.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.
This README will be filled in with usage instructions, the final feature
list, and results as each build phase completes.
