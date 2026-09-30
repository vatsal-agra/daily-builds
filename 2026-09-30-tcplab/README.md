# tcplab — a from-scratch TCP stack (in progress)

Status: **Phase 1 (plan) complete.** See [PLAN.md](PLAN.md).

A zero-dependency Rust implementation of TCP — wire format, state machine, RTO, reassembly,
flow control, Tahoe/Reno/NewReno/CUBIC — running over a deterministic simulated lossy network.
