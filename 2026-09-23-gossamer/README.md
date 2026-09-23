# Gossamer

A from-scratch Dynamo-style leaderless distributed key-value store: consistent
hashing with virtual nodes, vector clocks for causality, tunable N/R/W quorum
reads/writes, and gossip-based failure detection — plus hinted handoff,
Merkle-tree anti-entropy repair, and a live dashboard as stretch goals.

**Status: Phase 4 (stretch features + polish) complete.** All 4 required
features plus both stretch features are implemented and demonstrably working
end-to-end against a real 5-node cluster of independent OS subprocesses:

- Consistent hashing ring with virtual nodes
- Vector clocks for causal conflict detection (real siblings, not LWW)
- Quorum reads/writes (tunable N/R/W) with background read-repair
- Gossip-based failure detection (fully decentralized, no leader)
- Hinted handoff to a substitute node when a replica is down
- Merkle-tree anti-entropy repair for a node that missed writes entirely
- A live dashboard (`/dashboard` on any node): the hash ring, per-node
  gossip views, live request routing, and real vector-clock conflicts as
  they happen — no build step, polls each node's own `/admin/status` and
  `/admin/events` directly

See [PLAN.md](PLAN.md) for the full concept and architecture, and
[REVIEW.md](REVIEW.md) for the adversarial review: 7 real bugs found and
fixed (a silent data-loss bug in hinted-handoff flush retry, a URL-encoding
bug corrupting keys with reserved characters, missing input validation, a
metrics race, and more), plus a test-suite flakiness investigation, each
with a regression test or a documented before/after stress-test result.

## Try it

```
python3 -m unittest discover -s tests   # 64 unit + real multi-process integration tests
python3 -m gossamer.demo                # the flagship narrated 5-node demo
./demo.sh                                # everything above, end to end (+ dashboard smoke test)
```

To see the live dashboard yourself:

```
python3 -m gossamer.cli cluster start --nodes A,B,C,D,E --base-port 9500
open http://127.0.0.1:9500/dashboard      # (or just visit it in a browser)
python3 -m gossamer.cli put mykey '"hello"'
python3 -m gossamer.cli cluster stop
```

Verification (Phase 5) and shipping (Phase 6) are next.
