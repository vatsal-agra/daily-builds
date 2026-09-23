# Gossamer

A from-scratch Dynamo-style leaderless distributed key-value store: consistent
hashing with virtual nodes, vector clocks for causality, tunable N/R/W quorum
reads/writes, and gossip-based failure detection — plus hinted handoff and
Merkle-tree anti-entropy repair and a live dashboard as stretch goals.

**Status: Phase 3 (adversarial review) complete.** All 4 required features
plus both stretch features are implemented and demonstrably working
end-to-end against a real 5-node cluster of independent OS subprocesses:

- Consistent hashing ring with virtual nodes
- Vector clocks for causal conflict detection (real siblings, not LWW)
- Quorum reads/writes (tunable N/R/W) with background read-repair
- Gossip-based failure detection (fully decentralized, no leader)
- Hinted handoff to a substitute node when a replica is down
- Merkle-tree anti-entropy repair for a node that missed writes entirely

See [PLAN.md](PLAN.md) for the full concept and architecture.

## Try it

```
python3 -m unittest discover -s tests   # 64 unit + real multi-process integration tests
python3 -m gossamer.demo                # the flagship narrated 5-node demo
./demo.sh                                # everything above, end to end
```

See [REVIEW.md](REVIEW.md) for the adversarial review: 7 real bugs found
(including a silent data-loss bug in hinted-handoff flush retry, and a
URL-encoding bug corrupting keys with reserved characters) and fixed, each
with a regression test. Stretch-feature polish (the live dashboard) is next.
