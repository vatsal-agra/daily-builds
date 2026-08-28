# LedgerLine — a from-scratch proof-of-work blockchain & cryptocurrency network

## Concept

A real proof-of-work cryptocurrency, built from the ground up: elliptic-curve
wallets that actually sign transactions, a UTXO ledger, blocks linked by
proof-of-work and validated the way a real node validates them, and — the
part that makes it more than a toy — a genuine peer-to-peer network of
independent nodes on localhost sockets that gossip blocks and transactions,
mine in parallel, and resolve forks by the longest-valid-chain rule. You can
partition the network, watch two chains grow independently, reconnect it,
and watch a real reorg happen with your own eyes in the explorer UI.

## Why this is interesting (and why today)

This repository has, at this point, built almost every other classic
"systems from scratch" project — SAT solvers (x5), compression codecs (x3),
chess engines (x2), version control systems (x2), a spreadsheet, a search
engine, a CPU pipeline simulator, a WASM VM, nine transformer language
models, a Raft consensus simulator, and standalone crypto-primitive suites
(AES/RSA/ECDSA/ChaCha20). Checked against `LEDGER.md`: no prior entry is a
blockchain, a cryptocurrency, a UTXO ledger, or uses proof-of-work — this is
a genuinely new domain.

It's also a nice synthesis point: it reuses the *idea* of "from-scratch
crypto primitives" (Cryptex/Ironkey) and "deterministic distributed system
with fault injection" (Quorum's Raft simulator) but combines them into
something neither one was — an economically-motivated, adversarial,
probabilistic consensus protocol (Nakamoto consensus) instead of a
leader-election one (Raft), with real money (UTXOs) at stake, which makes
forks and double-spends *matter* in a way they don't in a CRUD app.

## Scope decision on "from scratch"

SHA-256 has already been implemented from scratch twice in this repo
(Ironkey, Shannon) and isn't the novel part of a blockchain — the novel part
is the *protocol*: PoW mining, chain-work comparison, UTXO validation, and
peer consensus. So block/transaction hashing uses `hashlib.sha256` (as
"SHA-256d", i.e. hashed twice, exactly like real Bitcoin) so effort goes into
the protocol layer instead of re-deriving a hash function for a third time.

In exchange, this project implements something no prior entry has: **ECDSA
over secp256k1 — Bitcoin's actual curve** — completely from scratch
(finite-field point arithmetic, scalar multiplication via double-and-add,
modular inverse via Fermat's little theorem, RFC 6979 deterministic nonce
generation, DER signature encoding, Base58Check address encoding). This is
what a real wallet uses to prove ownership of coins, and it is the load-
bearing crypto of the whole project, not a demo primitive sitting next to
seven others.

## Architecture

```
ledgerline/
  ecdsa.py       secp256k1 point math, keygen, RFC6979 sign, verify, DER (en/de)code
  crypto.py      sha256d, RIPEMD-160-free hash160 (double-sha256 + stdlib truncation),
                 Base58Check encode/decode, address <-> pubkey-hash
  merkle.py      Merkle tree build + root + inclusion proof
  transaction.py UTXO transaction model: TxIn/TxOut, coinbase, serialization,
                 signing (sighash), signature verification
  block.py       BlockHeader + Block, PoW target math, mining loop, header validation
  chain.py       Blockchain: UTXO set, full block validation, cumulative-work
                 comparison, reorg (fork switch), difficulty retarget
  mempool.py     pending-tx pool, fee-based selection for block templates
  wallet.py      key/address management, UTXO scan, balance, send-transaction builder
  node.py        P2P: TCP socket server + client, line-delimited JSON protocol
                 (VERSION/INV/GETDATA/BLOCK/TX/GETCHAIN), gossip + relay, per-node
                 mining thread, partition/reconnect controls for demos
  explorer_server.py  stdlib http.server backend exposing node/chain state as JSON
  static/explorer.html  self-contained dark-themed single-page block explorer UI
  cli.py         `ledgerline` command: keygen / mine / network / explorer / demo

tests/           unittest suite: ecdsa, merkle, transaction, block, chain, network
demo.sh          end-to-end scripted walkthrough of every feature
```

Design principle carried over from this repo's server-backed UI pattern
(Gambit's chess board, Formulate's spreadsheet, Impulse's physics sandbox):
the browser never computes chain state — the explorer is a thin JSON/SSE
client over the real Python node, so what you see in the UI is provably
what the node itself believes.

## Feature list

**Required (4):**

1. **Blockchain core + proof-of-work mining** — block header (prev hash,
   Merkle root, timestamp, bits/target, nonce, height), a real Merkle tree
   over transactions, a genuine PoW search (increment nonce until
   `sha256d(header) < target`), and full block validation (PoW satisfied,
   Merkle root matches transactions, prev-hash links, timestamp sanity,
   height correct).

2. **ECDSA (secp256k1) wallets + UTXO transactions** — from-scratch elliptic
   curve arithmetic and RFC 6979 deterministic signing, Base58Check
   addresses, a UTXO ledger (transactions spend prior outputs and create new
   ones), coinbase block-reward transactions, and full transaction
   validation (signature verifies against the claimed input's locking
   address, inputs exist and are unspent, no double-spend within a block,
   sum(inputs) >= sum(outputs), fee = difference).

3. **Peer-to-peer network with fork resolution** — multiple independent node
   processes/threads on real localhost TCP sockets, each with its own chain,
   UTXO set, mempool, and mining thread, gossiping blocks and transactions
   to peers; nodes can be network-partitioned and reconnected; the
   heaviest-cumulative-work chain wins on reconnect, with a real reorg
   (rolling back the losing branch's transactions into the mempool).

4. **Mempool + live block explorer web UI** — a fee-prioritized pending-
   transaction pool that miners draw block templates from, and a real-time
   browser explorer (blocks, transactions, per-address balances, mempool,
   per-node peer/chain-tip status) backed by the actual running node state.

**Stretch (2, both attempted):**

5. **Difficulty retargeting** — Bitcoin-style: every N blocks, compare
   actual elapsed time to expected time and adjust the target
   (clamped to a max 4x swing per retarget), demonstrated by adding more
   mining power mid-run and showing the target tighten in response.

6. **Network partition / double-spend / reorg demo** — a scripted attack:
   partition the network, spend the same UTXO on both partitions, reconnect,
   and show the losing branch's now-invalid transaction evaporate from
   history while its coins return to the mempool as unspent — a live
   demonstration of why merchants wait for confirmations.

## Verification plan

Unit tests for curve arithmetic (known test vectors + round-trip sign/verify
+ tamper detection), Merkle proofs, transaction/block validation (positive
and adversarial/malformed cases), chain reorg correctness (cumulative work,
not just height, decides the winner), and an integration test that spins up
a real multi-node network over sockets, mines on both sides of a partition,
reconnects, and asserts convergence to one chain. `demo.sh` drives the real
CLI end to end, including the network partition/reorg scenario and a
headless-Chromium screenshot check of the explorer UI.
