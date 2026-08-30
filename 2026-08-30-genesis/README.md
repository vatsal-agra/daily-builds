# Genesis

A from-scratch blockchain: proof-of-work mining with real difficulty
retargeting, a UTXO ledger authorized by from-scratch secp256k1 ECDSA
signatures, Merkle-tree transaction commitments with inclusion proofs, and
a simulated multi-node P2P network that reaches consensus via the
longest-valid-chain rule — including real chain reorgs.

**Status: Phase 2 (core build) complete.** All four required features are
implemented and covered by an automated test suite:

1. **Proof-of-work + difficulty retargeting** (`src/block.py`,
   `src/blockchain.py`) — SHA-256d header mining against a numeric target,
   retargeted every 10 blocks from actual vs. expected elapsed time.
2. **UTXO ledger + from-scratch secp256k1 ECDSA** (`src/crypto.py`,
   `src/transaction.py`) — every spend must carry a signature that
   verifies against the key the output was locked to.
3. **Merkle tree commitments + inclusion proofs** (`src/merkle.py`).
4. **Multi-node P2P consensus with fork resolution** (`src/network.py`,
   `src/node.py`, `src/blockchain.py`) — a seeded discrete-event network of
   nodes that mine independently, gossip, and reorg onto whichever chain
   has the most cumulative work.

77 unit tests pass (`python3 -m unittest discover -s tests`), including a
genuine fork + reorg (a losing fork's transactions are undone, the winning
fork's applied) and a partition-then-heal scenario. See `PLAN.md` for the
full architecture. Next: adversarial review, then stretch features
(wallet CLI, live block-explorer UI) and final polish.
