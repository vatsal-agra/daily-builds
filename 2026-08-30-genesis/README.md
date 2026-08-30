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

**Status: Phase 3 (adversarial review) complete.** Attacked the Phase 2
build as a hostile reviewer and found 5 real issues — genesis block PoW/
merkle-root going completely unvalidated, the simulated network passing
live Python objects instead of real serialized bytes (making the wire
format dead code), a directory-traversal hole in the explorer's static
file handler plus an unnecessary `0.0.0.0` bind, gossip echoing every
message straight back to its sender, and an unconditional full-chain
replay on every accepted block instead of only competing branches — all
fixed, with regression tests added. Full findings + fixes in `REVIEW.md`.

**Status: Phase 4 (stretch + polish) complete.** Both planned stretch
features are implemented:

5. **A genuinely usable wallet CLI** (`cli.py`) — on-disk persistence
   (`src/persistence.py`) means `send` in one process invocation and
   `mine` in the next actually see each other, the way a real wallet has
   to work. `python3 cli.py init|address|balance|status|history|send|mine`.
2. **A live, self-contained block-explorer web UI** (`src/server.py` +
   `static/index.html`) — a real 3-node network mining, gossiping, forking,
   and reconverging live behind a stdlib `http.server`, with zero
   blockchain logic duplicated in the browser (every number on the page is
   a JSON read from the real chain). `python3 cli.py serve`.

Running the live explorer end to end (not just reading the code) surfaced
two more real bugs beyond Phase 3's five — gossip silently never being
delivered, and difficulty drifting easier forever instead of settling —
both fixed and covered by new tests (`REVIEW.md`, findings #6-7).

87 unit/integration tests pass (`python3 -m unittest discover -s tests`),
including a genuine fork + reorg (a losing fork's transactions are undone,
the winning fork's applied), a partition-then-heal scenario, and a live
HTTP server spin-up. See `PLAN.md` for the full architecture.

**Status: Phase 5 (verification) complete.** `./demo.sh` runs everything
end to end in one command — the full test suite, the narrated
cross-feature demonstration, a real wallet-CLI session (init → mine →
send → mine → balance, using a throwaway temp data directory), and a live
spin-up of the block-explorer server (real HTTP requests against it,
including the path-traversal regression check) — and exits non-zero on
the first failure. All sections pass. Next: final ship.
