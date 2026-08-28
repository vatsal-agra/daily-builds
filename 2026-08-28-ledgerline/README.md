# LedgerLine

A from-scratch proof-of-work blockchain and cryptocurrency network — real
secp256k1 ECDSA wallets, a UTXO ledger, proof-of-work mining, and a
genuine multi-node peer-to-peer network (real localhost TCP sockets, not
simulated message-passing) that gossips blocks and transactions and
resolves forks by the longest-valid-chain (highest cumulative work) rule.
You can partition the network, watch two chains grow independently, spend
the same coin on both sides, reconnect it, and watch a real reorg settle
the double-spend live in the browser explorer.

## What it is

Six pieces, each a real implementation of the thing it's named for, not a
stand-in:

1. **Blockchain core + proof-of-work mining** (`block.py`, `chain.py`) — a
   real Merkle tree over each block's transactions, a genuine PoW search
   (increment a nonce until `sha256d(header) < target`), and full block
   validation (PoW satisfied, Merkle root matches, prev-hash links,
   height correct, every transaction structurally valid).
2. **secp256k1 ECDSA wallets + UTXO transactions** (`ecdsa.py`,
   `transaction.py`) — elliptic-curve point arithmetic, RFC 6979
   deterministic signing, and Base58Check addresses built entirely from
   scratch (no `ecdsa`/`cryptography`/`coincurve` package), independently
   cross-verified against the PyPI `ecdsa` library (pubkey derivation,
   signature interop in both directions, and even the RFC 6979 nonce
   itself, bit-for-bit identical). A UTXO ledger on top: transactions
   spend prior outputs and create new ones, with coinbase block rewards
   and full validation (signatures, ownership, no double-spends,
   inputs ≥ outputs).
3. **Peer-to-peer network with fork resolution** (`node.py`, `network.py`)
   — independent nodes on real localhost TCP sockets, each with its own
   chain, UTXO set, mempool, and mining thread, gossiping blocks and
   transactions to peers; nodes can be network-partitioned and
   reconnected, with the heaviest-cumulative-work chain winning on
   reconnect via a genuine reorg (rolling the losing branch's
   transactions back into the mempool).
4. **Mempool + live web block explorer** (`mempool.py`,
   `explorer_server.py`, `static/explorer.html`) — a fee-prioritized
   pending-transaction pool, and a real-time dark-themed browser UI
   backed by the actual running nodes (same server-backed-UI pattern as
   this repo's Gambit/Formulate/Impulse: the browser computes nothing,
   every view is a JSON round trip to real Python objects).
5. **Live double-spend across a partition, resolved by reorg** (stretch)
   — the exact same UTXO spent two conflicting ways on either side of a
   real network partition; reconnecting triggers a genuine reorg that
   settles on one winner and evaporates the loser — a live demonstration
   of why merchants wait for confirmations.
6. **Bitcoin-style difficulty retargeting** (stretch) — off by default
   (fixed difficulty), opt-in with `--retarget`; every 10 blocks, compares
   actual vs. expected elapsed time and adjusts the target (clamped to a
   4x swing), demonstrated live: `ledgerline demo` spawns extra miners as
   genuine separate OS processes (not just threads — CPython's GIL caps
   concurrent *threads* in one process to roughly one thread's worth of
   real throughput no matter how many you add) so the hash-power increase
   is real, and watches difficulty climb in response.

## How to run it

```bash
cd 2026-08-28-ledgerline

python3 -m ledgerline.cli keygen                          # generate a wallet
python3 -m ledgerline.cli network --nodes 4 --seconds 30   # headless multi-node network in the terminal
python3 -m ledgerline.cli explorer --nodes 4               # network + live web explorer at http://127.0.0.1:8765
python3 -m ledgerline.cli demo                              # scripted end-to-end walkthrough of every feature
python3 -m ledgerline.cli test                              # unit test suite (98 tests)
./demo.sh                                                    # everything above + a headless-Chromium explorer check
```

Useful flags: `--nodes N`, `--bits N` (PoW difficulty), `--retarget`
(enable difficulty retargeting), `--wallet FILE` (persist node0's address
across runs). Run any subcommand with `--help` for the full list.

In the explorer, click a node card to inspect its chain/mempool, send a
transaction to another node's address from the send-coins panel, or
click node names into a partition group and hit "Isolate selected group"
to watch the network split and fork live — then "Heal network" to watch
it reorg back to one chain.

## Full feature list

**Required (4/4):** PoW block mining + Merkle trees; secp256k1 ECDSA
wallets + UTXO transactions; a real multi-node P2P network with
cumulative-work fork resolution; a fee-prioritized mempool + live web
explorer.

**Stretch (2/2):** a live double-spend across a partition resolved by
reorg; Bitcoin-style difficulty retargeting responding to a real
hashrate change.

**Plus:** partition/reconnect controls (CLI and explorer UI); an
interactive send-coins form backed by real signed transactions; CLI
input validation with clean errors instead of tracebacks or hangs;
`--wallet` persistence so an address survives across separate runs;
independent cross-verification of the ECDSA implementation against the
`ecdsa` PyPI package; a 98-test unit suite plus `demo.sh`'s full
end-to-end, headless-Chromium-verified run.

See [`REVIEW.md`](./REVIEW.md) for the adversarial review: 9 real bugs
found and fixed across every phase of this build (3 critical — a
negative-output money-creation exploit, a mempool-poisoning bug that
could permanently cripple a node's own mining, and multi-input
transactions being fundamentally broken), each with a regression test or
a repeated live re-validation proving the fix.

## Why I chose this today

Checked against `LEDGER.md`: this repository has, at this point, built
almost every other classic "systems from scratch" project — five SAT
solvers, three compression codecs, two chess engines, two version control
systems, a spreadsheet, a search engine, a CPU pipeline simulator, a WASM
VM, nine transformer language models, a Raft consensus simulator, and
standalone crypto-primitive suites. None of them is a blockchain, a
UTXO ledger, or uses proof-of-work — a genuinely open domain. It's also a
nice synthesis point: it reuses this repo's "from-scratch crypto
primitives" lineage (Cryptex, Ironkey) and "deterministic distributed
system with fault injection" lineage (Quorum's Raft simulator), but
combines them into something neither one was — an economically-motivated,
adversarial, *probabilistic* consensus protocol (Nakamoto consensus,
instead of leader-election) where real money (UTXOs) is at stake, which
is exactly what makes forks and double-spends matter in a way they don't
in a CRUD app or a toy state machine.

## Where a human could take this next

- **A real scripting layer.** Transactions are currently fixed-shape
  (sign, check ownership, spend). A minimal Bitcoin-Script-style stack
  VM for locking/unlocking scripts (P2PKH, multisig, timelocks) would
  turn this from "a currency" into "a programmable currency" without
  touching the consensus core.
- **Persistence.** Everything lives in memory; a node restart loses its
  chain. A simple append-only block-file format (`chain.py` already has
  clean serialize/deserialize via `to_dict`/`from_dict`) plus a UTXO-set
  snapshot would make nodes survive restarts, and is a natural on-ramp to
  benchmarking against a real disk-backed workload.
- **Real networking beyond localhost.** The P2P layer works over genuine
  TCP sockets already — pointing nodes at real IPs/ports instead of
  `127.0.0.1` and adding peer discovery (a seed list, or a simple gossip-
  based peer exchange message) would make this a real, if small, testnet.
- **SPV / light clients.** `merkle.py` already implements Merkle inclusion
  proofs (`merkle_proof`/`verify_merkle_proof`) but nothing in the wire
  protocol serves them yet — a `get_merkle_proof` message and a client
  that verifies "this transaction is in this block" against just block
  headers (not the full UTXO set) is most of an SPV wallet.
- **Mining pools / stratum-style work distribution.** The mining loop
  currently builds its own full block templates; splitting "find a
  nonce" from "assemble a block" (the way real mining pools split work
  across many workers) would be a natural extension of the existing
  `mine_block` function.
