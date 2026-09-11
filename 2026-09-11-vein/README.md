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

**Status: Phase 4 (Stretch + polish) complete.** Both stretch features
from [`PLAN.md`](PLAN.md) are shipped, not just one:

5. **Live block-explorer web UI** (`vein/explorer/explorer.html`) — a
   self-contained, dark-themed page with zero build step, backed entirely
   by one node's real RPC (chain view, per-block transaction detail in a
   modal, live mempool, balance lookup, peer/severed status, chain-tips
   view, and a live SSE event log) — verified with a real headless-
   Chromium pass (zero console errors) against a live mining node,
   including clicking into a real block and looking up a real balance.
6. **CLI wallet + orchestrated network-partition demo** (`vein wallet
   new/address/balance/send`, `vein partition-demo`) — verified
   end-to-end: a real wallet-to-wallet payment, mined and confirmed on a
   live node, RPC-queried back out.

Polish: clean, non-traceback error handling across the CLI (missing
wallet file, invalid address, unreachable RPC, zero/negative amount,
insufficient funds, no spendable coins, malformed RPC input) and the
explorer degrades gracefully with no node connected.

**Status: Phase 5 (Verification) complete.** `demo.sh` runs 5 checks,
each exercising real, live behavior (nothing mocked): the 70-test unit
suite; the single-process core walkthrough; a real node with a real
wallet-to-wallet payment confirmed on-chain and a real headless-Chromium
pass over the block explorer with zero console errors; the 4-subprocess
network-partition/double-spend/reorg demo; and clean CLI error handling
on bad input. Run twice consecutively with zero failures both times.

```
./demo.sh
```

Next: Phase 6 (ship).
