# tcplab — a from-scratch TCP stack (in progress)

**Status: Phase 3 complete** — required features built, adversarially reviewed and hardened.
See [PLAN.md](PLAN.md) (roadmap) and [REVIEW.md](REVIEW.md) (what the hostile review found and fixed).

A zero-dependency Rust implementation of TCP running over a deterministic simulated network.

## Required features (done)
1. **Wire codec** — real 20-byte TCP header, MSS + window-scale options, ones'-complement checksum with
   IPv4 pseudo-header, malformed-input rejection, wrap-safe sequence arithmetic.
2. **Connection state machine** — all 11 RFC 793 states: 3-way handshake, simultaneous open, graceful
   close, simultaneous close, TIME_WAIT (RFC 1337 hardened), RST / connection refused, SYN retry + timeout.
3. **Reliable in-order byte stream** — cumulative ACKs, RFC 6298 RTO (Karn, exponential backoff),
   fast retransmit, out-of-order reassembly, tolerance for loss / duplication / reordering / corruption,
   32-bit sequence wraparound.
4. **Congestion + flow control** — slow start, congestion avoidance, Tahoe / Reno / NewReno (+ CUBIC),
   receiver window with scaling, silly-window avoidance, zero-window persist probes.

## Try it
```
cargo run --release -- handshake                       # annotated open → data → close
cargo run --release -- run --scenario bottleneck --algo reno
cargo run --release -- compare --scenario satellite
cargo test                                             # debug build: overflow traps on
```
