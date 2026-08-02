# Concord

A cryptocurrency and blockchain built entirely from scratch in pure
Python: real secp256k1 elliptic-curve cryptography (no `cryptography` /
`ecdsa` / `secp256k1` package), a UTXO ledger with full validation,
proof-of-work mining with real difficulty retargeting, and a genuine
multi-node peer-to-peer network — real TCP sockets, real threads — that
gossips blocks and transactions and resolves forks by cumulative
proof-of-work. Ships with a live block explorer and a scripted
double-spend attack simulation that measures whether the defenses
actually hold.

## Quick start

```bash
cd 2026-08-02-concord
export PYTHONPATH=.

# the fastest way to see everything working: a scripted 3-node network —
# mining, gossip, a transaction propagating and confirming, and an
# independently-verified Merkle inclusion proof
python3 -m concord.demo

# a scripted attack: a mempool double-spend race, and a private-chain
# "pay -> 1 confirmation -> try to reverse it" race against a 3-miner
# honest network — the outcome is measured and printed, not asserted
python3 -m concord.attack_demo

# the full check: unit/integration tests, both demos above, a real CLI
# walkthrough (including error paths), and a headless-browser check of
# the explorer UI
./demo.sh
```

### Running your own network by hand

```bash
python3 -m concord.cli wallet-new --out alice.json
ADDR=$(python3 -m concord.cli wallet-address --wallet alice.json)
python3 -m concord.cli genesis-create --address "$ADDR" --amount 1000 --out genesis.json

# starts a P2P node + JSON API + live block explorer, and mines to alice
python3 -m concord.cli node --genesis genesis.json \
  --p2p-port 9000 --api-port 8000 --mine --wallet alice.json
```

Then open `http://127.0.0.1:8000/` in a browser for the live explorer,
or in another terminal:

```bash
python3 -m concord.cli wallet-new --out bob.json
BOB=$(python3 -m concord.cli wallet-address --wallet bob.json)
python3 -m concord.cli send --api http://127.0.0.1:8000 --wallet alice.json --to "$BOB" --amount 100
python3 -m concord.cli wallet-balance --wallet bob.json --api http://127.0.0.1:8000
```

A second node joins the same network with `--peer 127.0.0.1:9000`.

## Why this, today

This repo has built a large amount of "systems from scratch" —
compilers, a JIT backend, chess engines, ray tracers, a fluid simulator,
a Raft consensus simulator, several from-scratch transformers, search
engines, a git clone, a spreadsheet. It had never built a system whose
entire point is **adversarial, decentralized trust**: independent nodes
that don't trust each other, agreeing on one shared history via
computational cost rather than a designated leader — a materially
different problem from Raft's benign-leader-election consensus. It's
also the first project here to implement public-key cryptography's
actual field/group arithmetic (modular inverse, elliptic-curve point
addition/doubling, scalar multiplication) rather than symmetric ciphers
(this repo's Cryptex/Ironkey did AES/RSA/PBKDF2, not elliptic curves).

## Feature list

**Required (all 4 shipped):**

1. **secp256k1 cryptography from scratch** — finite-field arithmetic,
   EC point add/double/scalar-mult, ECDSA keygen/sign/verify (with
   canonical low-s enforcement against signature malleability — see
   REVIEW.md finding #6), and a from-scratch base58check address
   encoder. No crypto libraries beyond `hashlib`'s SHA-256.
2. **UTXO blockchain with full validation** — Merkle-committed
   transaction lists, PoW-linked headers, and `Blockchain.add_block`
   rejecting bad PoW, wrong difficulty target, wrong height, timestamps
   before the parent or too far in the future, any already-spent or
   unknown input, invalid signatures, a pubkey that doesn't hash to the
   UTXO's owning address, outputs exceeding inputs, and coinbase overpay.
3. **Proof-of-work mining with real difficulty retargeting** — a
   threaded miner searching nonces until `hash(header) <= target`, with
   Bitcoin-style retargeting every 5 blocks based on real observed block
   time vs. a 1-second target.
4. **Real multi-node P2P network with fork resolution** — independent
   node threads on real TCP sockets running a gossip protocol (inventory
   announce → fetch → validate → relay, with a seen-set against flood
   loops), full-chain sync on connect *and* whenever gossip reveals a
   node has fallen behind by more than one block, and fork choice by
   cumulative proof-of-work — including actually orphaning blocks and
   restoring their transactions to the mempool on reorg.

**Stretch (both shipped):**

5. **Live block explorer** — a dark/light-aware single-page UI backed by
   a real JSON API (`concord/explorer.py`): chain view, block detail, a
   Merkle-proof visualizer that *recomputes the proof in the browser*
   via the real Web Crypto `SHA-256` primitive (not just displaying a
   server claim), live mempool, and a peer-connectivity graph.
6. **Double-spend attack simulation** (`concord/attack_demo.py`) — a
   mempool-level race (two transactions spending the same input,
   broadcast to different nodes) and a private-chain race (pay → wait
   for 1 confirmation → privately mine an alternate history that pays
   the attacker instead, racing against a 3-miner honest network). Both
   outcomes are measured and printed, not hard-coded.

## How it was verified

- **109 unit/integration tests** (`tests/`, run via
  `python3 -m unittest discover -s tests`): curve arithmetic and ECDSA
  (including the malleability and out-of-range-point rejections), Merkle
  trees and proofs, transaction signing/tamper-detection, every
  `Blockchain.add_block` rejection path, fork/reorg with orphaned-tx
  restoration, mempool double-spend/conflict-pruning, the miner's
  candidate-selection logic, wallet coin selection and error handling,
  real 2-node network sync/gossip/late-join scenarios (including a
  regression test for the silent-forking bug in REVIEW.md finding #1),
  and the explorer's full JSON API.
- **`concord/demo.py`** — a real 3-node network: mine, gossip-sync,
  propagate and confirm a transaction, verify balances agree
  independently on all 3 nodes, and independently re-verify a Merkle
  inclusion proof against the live API.
- **`concord/attack_demo.py`** — the two attack scenarios above, with
  real assertions on the measured outcome.
- **`demo.sh`** — runs all of the above plus a real CLI walkthrough
  (wallet creation, genesis, a mining node, a signed transaction, and
  every error path: invalid address, insufficient funds, missing
  wallet file) and a headless-Chromium check of the explorer UI
  (`tests/check_explorer_ui.js`) that clicks through to a real
  multi-transaction block and confirms the Merkle proof panel actually
  recomputed and matched, with zero console errors.
- **`REVIEW.md`** — the adversarial review: 10 real findings (including
  one critical silent-permanent-forking bug caught while building the
  very first demo, and a live ECDSA signature-malleability gap), what
  was fixed and why, and what was deliberately left as a disclosed
  limitation rather than hidden.

## Known, disclosed limitations

See "Deliberately not changed" in [REVIEW.md](REVIEW.md) for the full
list with reasoning — in short: the mempool has no fee-market ordering
(FIFO) and no support for spending an unconfirmed parent's output
(rejected safely, not silently); addresses use `SHA256(SHA256(pubkey))`
rather than `RIPEMD160(SHA256(pubkey))` because Python's `hashlib` does
not guarantee RIPEMD-160 availability; and difficulty is tuned for a
fast demo, not real-world security.

## Where a human could take this next

- **Fee-market mempool.** Prioritize `select_for_block` by fee-per-byte
  instead of FIFO, and support mempool-chaining (spending an unconfirmed
  parent's change output) with proper ancestor/descendant tracking.
- **SPV / light clients.** The wire format already carries a Merkle root
  per block; a light client that verifies proofs instead of downloading
  full blocks is most of the way there architecturally.
- **Real network transport.** The P2P layer has no encryption,
  authentication, or NAT traversal — it's designed for a trusted-LAN or
  localhost demo. A real deployment would want TLS and peer discovery
  (DNS seeds / a Kademlia-style DHT) instead of manually specified
  `--peer` addresses.
- **Script-based spending conditions.** Outputs currently pay a single
  address unconditionally; a small stack-based script language (even a
  minimal `OP_CHECKSIG`-only subset) would enable multisig and
  timelocks.
- **Persistence.** Everything currently lives in memory; a node
  restart loses the chain. Swapping `Blockchain`'s in-memory dicts for
  an on-disk store (even SQLite) would make it survive restarts.
