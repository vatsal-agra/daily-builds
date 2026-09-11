# Vein

A from-scratch Proof-of-Work blockchain — real secp256k1 ECDSA, a UTXO
ledger with a tiny Bitcoin-Script-style VM, PoW mining with difficulty
retargeting, and a multi-process P2P gossip network that reconciles forks
by cumulative work (a real reorg, including UTXO rollback), the way real
Bitcoin nodes do.

See [`PLAN.md`](PLAN.md) for the full architecture and feature list.

**Status: Phase 2 (Core build) complete.** All 4 required features are
implemented and demonstrably work end-to-end:

1. **secp256k1 + ECDSA from scratch** (`vein/crypto/`) — field/point
   arithmetic, RFC 6979 deterministic signing, SHA-256 + RIPEMD-160
   (also from scratch), Base58Check addresses.
2. **UTXO ledger + Script VM** (`vein/core/script.py`,
   `vein/core/transaction.py`) — P2PKH and bare multisig, a real
   stack-machine interpreter, the classic Satoshi-style sighash.
3. **PoW mining + validation** (`vein/core/block.py`,
   `vein/core/chain.py`) — compact-bits target encoding, a real nonce
   search, difficulty retargeting.
4. **P2P gossip network + fork resolution** (`vein/node/p2p.py`,
   `vein/core/chain.py`) — real TCP sockets between independent node
   processes, inv/getdata gossip, and reorg by greatest cumulative work
   with correct UTXO rollback/replay.

Try it:

```
python3 -m vein.cli demo              # single-process walkthrough (crypto, mining, a spend, retargeting)
python3 -m vein.cli partition-demo    # 4 real OS subprocesses, a network partition, a resolved double-spend
python3 -m unittest discover -s tests -v
```

**Status: Phase 3 (Adversarial review) complete.** See
[`REVIEW.md`](REVIEW.md) for the full write-up — 12 real issues found and
fixed, from a wrong hand-transcribed elliptic-curve constant to a genuine
unsynchronized-thread race condition in the P2P layer, surfaced mainly by
running `partition-demo` repeatedly under real concurrent load until it
broke. The multi-node partition demo now passes consistently across
repeated runs; the full test suite (70 tests) is green.

Next: Phase 4 (stretch features + polish).
