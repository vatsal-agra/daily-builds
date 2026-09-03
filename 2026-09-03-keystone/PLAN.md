# Keystone — a from-scratch blockchain & cryptocurrency protocol

## Concept

A complete proof-of-work cryptocurrency, built from raw bytes up: elliptic-curve
wallets, UTXO transactions, Merkle-tree blocks, a real difficulty-retargeting
mining loop, full chain validation with fork resolution, and a peer-to-peer
network of independent nodes gossiping over real TCP sockets — not a single
in-process "chain" object pretending to be a network.

## Why this is interesting (and new for this repo)

This repo has built an enormous amount of "from scratch" infrastructure —
language runtimes and VMs (Coil, Ember, Kiln), a CPU pipeline simulator
(Silicon), a Raft consensus simulator (Quorum), three separate version-control
systems, two full-text search engines, physics engines, path tracers, a
transformer LM, and — closest in spirit — Ironkey, a suite of cryptographic
*primitives* (SHA-256, AES, RSA, X25519) checked against NIST vectors and
OpenSSL.

None of that is a **distributed ledger**. Quorum simulates consensus over an
abstract log of opaque entries; it never has to answer "whose money is this,
and how do you prove you're allowed to spend it?" Ironkey builds the crypto
primitives but never builds a protocol on top of them that has to resist an
adversary economically, not just cryptographically (double-spends, forks,
orphaned blocks, an attacker with more hash power). Keystone is the first
build here where **byzantine, self-interested, only-locally-informed nodes**
have to converge on one shared truth with no central authority — the actual
hard problem Bitcoin solved in 2008, not a toy version of it.

The novelty is the *combination*, end to end and wired together for real:
- secp256k1 elliptic-curve wallets, implemented by hand (no `ecdsa`, no
  `cryptography`, no `secp256k1` package) — point addition/doubling, scalar
  multiplication, RFC 6979 deterministic-nonce ECDSA signing, and signature
  verification — cross-checked against real OpenSSL's own secp256k1
  implementation as an independent oracle (same verification pattern Ironkey
  used for its own primitives).
- RIPEMD-160 implemented from scratch for address hashing (OpenSSL 3 dropped
  it from its default provider, so there is no `hashlib.new('ripemd160')` to
  lean on in the first place — this one has to be hand-rolled to exist at
  all on this box). SHA-256 is *not* reimplemented — Ironkey already proved
  that primitive from scratch and cross-checked it against NIST vectors;
  redoing it here would be a repeat, not new work, so Keystone uses
  `hashlib.sha256` for the parts of the protocol (block/tx hashing, PoW,
  Merkle trees) where SHA-256 is just a building block, not the subject
  under test.
- A genuine UTXO ledger with signature-checked, script-locked outputs, a
  Merkle-tree-committed block format, and a mining loop that retargets
  difficulty from real elapsed wall-clock time, like Bitcoin's every-2016-block
  retarget, just on a compressed timescale.
- A real P2P network: independent node processes/threads, each with its own
  chain state and mempool, talking over real `socket` connections with a
  length-prefixed wire protocol (`VERSION`/`INV`/`GETDATA`/`TX`/`BLOCK`),
  gossiping transactions and blocks, resolving forks by cumulative proof-of-work
  (not just "block count"), and handling orphan blocks that arrive before
  their parent.

## Architecture

```
keystone/
  crypto.py      secp256k1 field/curve math, ECDSA sign+verify (RFC 6979),
                 RIPEMD-160 from scratch, base58check encoding
  wallet.py       keypair generation, address derivation, transaction signing
  script.py       tiny stack-based scripting VM (P2PKH + multisig opcodes)
  merkle.py       Merkle tree construction + inclusion proofs
  transaction.py  Transaction/TxIn/TxOut, txid, (de)serialization
  block.py        BlockHeader + Block, block hash, serialization
  pow.py          compact-bits difficulty target <-> integer, mining loop,
                  difficulty retarget algorithm
  utxo.py         UTXO set: apply/undo a block, double-spend + balance checks
  mempool.py      pending-transaction pool, fee-based ordering, eviction
  chain.py        Blockchain: block validation, best-chain selection by
                  cumulative work, reorg (undo/redo UTXO + mempool), orphan
                  pool for out-of-order blocks
  wire.py         length-prefixed JSON message framing over a TCP socket
  network.py      Node: real socket server + peer connections, gossip
                  (INV/GETDATA/TX/BLOCK), peer discovery via a seed list
  node.py         FullNode: wires chain + mempool + network + a miner thread
                  into one runnable node
  cli.py          `keystone` CLI: keygen, mine (single-node), demo-network
                  (spin up N real gossiping nodes), balance, explorer
  explorer.py     stretch: stdlib http.server-backed block-explorer web UI
                  (server holds all logic, browser is a thin view — same
                  pattern as this repo's Gambit/Formulate/Unify visualizers)
tests/            unittest suite, one file per module + integration tests
demo.sh           end-to-end runnable demo exercising every feature
```

## Feature list

**Required (core, must work end-to-end, no stubs):**

1. **secp256k1 wallets** — from-scratch elliptic-curve keygen, RFC-6979
   deterministic ECDSA signing, and verification; addresses derived via
   `RIPEMD-160(SHA-256(pubkey))` + base58check, matching Bitcoin's own
   address scheme. Cross-verified against real `openssl` as an independent
   oracle.
2. **UTXO transactions & Merkle-committed blocks** — transactions spend
   prior outputs by reference + signature, script-locked (P2PKH); blocks
   commit to their transaction set via a real Merkle root with inclusion
   proofs; genesis block anchors the chain.
3. **Proof-of-work mining with difficulty retarget** — a real mining loop
   searching nonces for a block hash under a compact-bits target, plus a
   Bitcoin-style periodic retarget that adjusts difficulty from actual
   elapsed mining time, and full chain validation (PoW, signatures, UTXO
   spends, no double-spends) that rejects any invalid block or transaction.
4. **P2P gossip network with fork resolution** — multiple independent node
   processes/threads on real TCP sockets exchange transactions and blocks,
   converge on the chain with the most cumulative proof-of-work (not the
   most blocks), correctly reorg when a competing fork overtakes the current
   tip, and resolve orphan blocks that arrive before their parent.

**Stretch (2+, at least 1 must ship):**

5. **Block explorer web UI** — `http.server`-backed, server-side-rendered
   (no client-side ledger logic) browser view of the live chain: blocks,
   transactions, address balances, and the current mempool.
6. **Scripting layer beyond plain P2PKH** — a small stack-based opcode VM
   (`OP_DUP`, `OP_HASH160`, `OP_EQUALVERIFY`, `OP_CHECKSIG`,
   `OP_CHECKMULTISIG`) so outputs can also be locked to *m-of-n* multisig,
   not just a single key.

## What "done" looks like

A demo network of several real nodes, started independently, mines blocks
concurrently, gossips them to convergence, has at least one real fork that
gets resolved by cumulative work, rejects at least one deliberately invalid
transaction (bad signature) and one deliberate double-spend, and ends with
every honest node agreeing on the same UTXO balances for every wallet —
verified programmatically, not by eyeballing log output.
