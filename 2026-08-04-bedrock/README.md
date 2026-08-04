# Bedrock

A from-scratch proof-of-work blockchain and cryptocurrency network:
secp256k1 elliptic-curve wallets, a UTXO ledger, real proof-of-work mining
with difficulty retargeting, full block/transaction consensus validation,
chain reorganization, a gossiping multi-process peer-to-peer network, and a
live block explorer + wallet web UI. Every piece of it — the curve
arithmetic, the ECDSA signatures, the Merkle trees, the mining loop, the
UTXO ledger, the fork-choice rule, the gossip protocol — is implemented
from first principles in pure Python 3 (stdlib only; no `pycoin`, no
`ecdsa`, no crypto library of any kind).

## What it is

Bedrock behaves like a tiny, real Nakamoto-consensus network. Miners
compete to find a block whose hash falls under a target that continuously
readjusts to a target block time. Wallets sign and broadcast transactions
that spend real, tracked, unspent outputs. Every node — whether it mined a
block itself or received it from a peer over the network — independently
re-validates everything before accepting it: the proof-of-work, the Merkle
commitment, every signature, every input's ownership, that nothing is
double-spent. When two miners find a block at the same height at the same
time, the network provably converges on whichever branch accumulates more
total work, exactly like the real thing.

## How to run it

```bash
# Run everything (recommended first step): tests, a scripted walkthrough of
# every feature, a CLI workflow, and a real 2-process P2P sync check.
./demo.sh

# Just the scripted feature walkthrough:
python3 -m bedrock.demo

# Just the test suite:
python3 -m unittest discover -s tests

# The CLI, with state persisted to a JSON file between invocations:
python3 -m bedrock.cli keygen                              # generate a wallet
python3 -m bedrock.cli mine <address>                       # mine a block
python3 -m bedrock.cli balance <address>
python3 -m bedrock.cli send <from> <to> 1.5 --fee 0.0001
python3 -m bedrock.cli chain                                 # summarize the chain
python3 -m bedrock.cli validate                              # re-validate the persisted chain from genesis

# The interactive block explorer + wallet web UI:
python3 -m bedrock.cli serve
# then open http://127.0.0.1:8420/

# A real P2P network of independent processes:
python3 -m bedrock.cli --data nodeA.json serve --listen --p2p-port 9001 --port 8001
python3 -m bedrock.cli --data nodeB.json serve --listen --p2p-port 9002 --port 8002 --peer 127.0.0.1:9001
# mine on either one's web UI or its /api/mine endpoint and watch both
# explorers' chain views converge on the same tip.
```

No dependencies to install — everything above runs on a stock Python 3
standard library.

## Feature list

**Required:**

1. **Core chain data structure** (`bedrock/block.py`, `bedrock/merkle.py`) —
   blocks with Merkle-committed transaction lists, canonical binary
   serialization, SHA-256d block hashing, a hash-linked chain from a
   deterministic hardcoded genesis block.
2. **Proof-of-work mining + real difficulty retargeting**
   (`bedrock/pow.py`) — a mining loop searching nonce space for a hash
   under a target, and Bitcoin-style retargeting (clamped to a 4x swing per
   interval) that adjusts the target toward a fixed block-time schedule
   based on actual elapsed mining time.
3. **secp256k1 wallets over a UTXO ledger** (`bedrock/crypto.py`,
   `bedrock/wallet.py`, `bedrock/transaction.py`) — hand-implemented
   elliptic-curve point arithmetic and ECDSA (with canonical low-S
   signatures, so no malleable second encoding of the same signature is
   ever accepted), from-scratch base58check address derivation, transaction
   signing/verification, coin selection, and balance computation, with a
   UTXO can only ever be spent once.
4. **Mempool, full validation, and chain reorganization**
   (`bedrock/chain.py`, `bedrock/mempool.py`, `bedrock/node.py`) — pending
   transactions validated against the live UTXO set before entering a
   block, every incoming block independently re-validated end to end, and
   automatic reorganization onto whichever known fork has the most
   cumulative proof-of-work when chains diverge.

**Stretch:**

5. **A real peer-to-peer network** (`bedrock/network.py`) — independent OS
   processes, each running a full Bedrock node with its own TCP server,
   gossiping new blocks and transactions to each other (with a seen-cache
   to stop infinite relay loops and per-message error isolation so one
   malformed message can't kill a peer connection) and converging on one
   chain — including recovering from a genuine simultaneous two-way fork
   once a tiebreaking block arrives.
6. **Interactive block explorer + wallet web UI** (`bedrock/explorer.py`)
   — a server-backed browser UI (the browser holds zero blockchain logic;
   every action is a real HTTP round trip to the running node) to browse
   blocks and transactions, watch the mempool live, create wallets, send
   coins, and mine — dark/light-theme aware, screenshot-verified in
   headless Chromium with zero console errors.

## Why I built this today

Every cryptographic primitive Bedrock needs — SHA-256, elliptic-curve
signatures — had already been built from scratch in this repo (Cryptex,
Ironkey), but never assembled into the system those primitives exist to
power. The closest neighbors in the daily-build history are Quorum (a
*permissioned*, single-leader Raft log — the opposite consensus shape from
permissionless proof-of-work) and the several from-scratch Git-like VCS
builds (content-addressed DAGs, but with no economic layer or network
protocol). Nothing here had combined *proof-of-work consensus*, *economic
double-spend prevention*, and *a real multi-process gossip network* into
one working system — that specific combination, not any one algorithm in
isolation, was today's genuinely open territory. It's also a domain with
unusually strong ground truth for adversarial testing: block hashes,
signatures, and Merkle roots are all independently re-derivable, and a
double-spend or forged signature has one unambiguous correct outcome
(reject) rather than a fuzzy "looks about right."

The adversarial review found exactly the kind of bug that ground truth is
good at catching: a critical signature-invalidation bug in multi-input
transactions, and a critical non-determinism bug in genesis block
construction that would have silently prevented any two independently
started Bedrock processes from ever syncing. Both were reproduced,
understood, and fixed — see [REVIEW.md](REVIEW.md) for the full account of
those and eight further issues.

## Where a human could take this next

- **Smart contracts / a scripting layer.** Outputs currently lock to a
  single address (P2PKH-shaped); a small stack-based script language
  (closer to Bitcoin Script, or a minimal EVM-like VM) would open up
  multisig, timelocks, and programmable spending conditions.
- **SPV / light clients.** The Merkle proof machinery
  (`bedrock/merkle.py`'s `merkle_proof`/`verify_merkle_proof`) is already
  there and tested but unused by the network layer — a light client could
  verify a transaction's inclusion without downloading full blocks.
- **Persistent, indexed storage.** The chain currently lives entirely in
  memory, replaying every block from genesis on load/reorg; a real
  on-disk, indexed store (paged files, an LSM-tree, or even just SQLite)
  would let Bedrock hold a chain far larger than fits in RAM, with
  incremental undo/redo instead of full-replay reorgs.
- **Fee-rate-aware mempool policy.** Block selection currently ranks by
  absolute fee, not fee-per-byte, and nothing enforces a minimum
  relay/mempool fee — real anti-spam economics would need both, plus a
  size cap on the mempool itself.
- **Compact block relay / SPV-style sync.** The P2P layer floods full raw
  blocks and does a naive whole-chain resync for a lagging peer; real
  systems relay just-in-time compact block encodings and headers-first
  sync.
- **A real wallet UX**, not a demo one — the explorer's wallets keep
  private keys in server memory for convenience; a serious wallet would
  need client-side key custody (hardware wallet support, an HD wallet
  derivation scheme, a real backup/recovery flow).

## Project layout

```
PLAN.md          architecture + feature plan (Phase 1)
REVIEW.md        adversarial review findings and fixes (Phase 3)
demo.sh          runs everything below in order
bedrock/         the implementation (see file-by-file docstrings)
tests/           134 unittest tests (unit, property/oracle-based, and
                 regression tests for every REVIEW.md finding)
```
