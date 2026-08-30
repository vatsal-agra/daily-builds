# Genesis

A blockchain built from scratch: real proof-of-work mining with difficulty
that retargets from actual mining speed, a UTXO ledger where every spend is
authorized by a from-scratch secp256k1 ECDSA signature, Merkle-tree
transaction commitments with inclusion proofs, and a simulated multi-node
P2P network that reaches consensus purely through the longest-cumulative-
work rule — including real chain reorgs when a competing fork wins.

No blockchain/crypto libraries anywhere (`ecdsa`, `cryptography`,
`web3`, ...). Pure Python 3 stdlib, `hashlib` for SHA-256 only (the elliptic
curve math, signing, verification, Merkle trees, the UTXO ledger, the PoW
mining loop, and the P2P consensus protocol are all hand-written).

## Why this, today

This repo has built a lot of cryptography (Cryptex, Ironkey) and a lot of
distributed consensus (Quorum's Raft) before, but never the specific
combination that makes a public blockchain interesting: nodes that don't
trust each other and have no leader, agreeing on one shared ledger purely
because the longest chain of expended computational work wins, where a
spend is only valid if signed by the key that actually owns the coin.
Three previously-unbuilt, independently-checkable ideas come together —
proof-of-work with a real difficulty feedback loop, UTXO+ECDSA
authorization, and leaderless multi-node fork resolution — see `PLAN.md`
for the full case.

## How to run it

```bash
cd 2026-08-30-genesis

# Everything, one command (tests, narrated demo, wallet CLI session, live server):
./demo.sh

# Or explore the pieces individually:
python3 -m unittest discover -s tests    # 87 unit/integration tests
python3 src/demo.py                       # narrated end-to-end demonstration

# A real wallet, persisted to disk across commands:
python3 cli.py init                       # create/open your local wallet + chain
python3 cli.py mine 3                     # mine 3 blocks, earn the block reward
python3 cli.py balance
python3 cli.py send <address> 12.5 --fee 2000
python3 cli.py mine                       # confirms the queued send

# The live 3-node block-explorer (http://127.0.0.1:8765):
python3 cli.py serve
```

The wallet CLI (`cli.py`) and the live explorer (`cli.py serve`) are two
separate demonstrations: the CLI is one persistent node you control by
hand; the explorer spins up its own independent 3-node network (Ada,
Grace, Katherine) that mines, gossips, forks, and reconverges on its own,
live, in front of you.

## Full feature list

**Required (core):**
1. **Proof-of-work mining with real difficulty retargeting**
   (`src/block.py`, `src/blockchain.py`) — SHA-256d header hashing against
   a 256-bit numeric target, retargeted every 10 blocks from actual vs.
   expected elapsed mining time, clamped to a 4× swing per window. Verified
   moving in *both* directions (harder under fast mining, easier under
   slow) with a real, un-clamped calculation, not a canned value.
2. **UTXO ledger + from-scratch secp256k1 ECDSA** (`src/crypto.py`,
   `src/transaction.py`) — the exact curve Bitcoin uses, implemented as
   plain-Python big-integer point arithmetic (no `ecdsa` package
   anywhere). Every transaction input must carry a signature that verifies
   against the public-key hash the referenced output actually locked to;
   base58check addresses; a from-scratch RIPEMD-160 fallback for
   environments where `hashlib` lacks it.
3. **Merkle tree commitment + inclusion proofs** (`src/merkle.py`) — every
   block's transactions commit to a Merkle root in the header; a proof
   lets you verify one transaction is in a block without the rest of it.
4. **Multi-node P2P consensus with fork resolution** (`src/network.py`,
   `src/node.py`, `src/blockchain.py`) — a seeded discrete-event network
   (same pattern as this repo's Quorum) where nodes mine independently,
   gossip blocks/transactions with simulated latency over real serialized
   bytes, and converge on whichever chain has the most cumulative
   proof-of-work — including a genuine reorg that unwinds a losing fork's
   transactions and re-applies the winning fork's.

**Stretch:**
5. **A genuinely usable wallet CLI** (`cli.py`, `src/persistence.py`) —
   on-disk chain + mempool + keypair persistence, so `send` in one process
   invocation and `mine` in the next actually see each other.
6. **A live, self-contained block-explorer web UI** (`src/server.py`,
   `static/index.html`) — a real 3-node network mining, gossiping,
   forking, and reconverging behind a stdlib `http.server`, zero
   blockchain logic duplicated in the browser (every number on the page is
   a JSON read from the real chain), live activity feed over
   Server-Sent Events, a working faucet + send-a-transaction form, and a
   Merkle-proof viewer per transaction.

**Extra, beyond the plan:**
- Double-spend rejection (both within a single block and against
  already-confirmed chain state), coinbase-overclaim rejection, orphan
  block buffering + automatic attachment, median-time-past + future-drift
  timestamp rules, and a network-partition/heal scenario that forces a
  real reorg on reconnect.

## Verification

87 automated tests (`python3 -m unittest discover -s tests`) plus
`src/demo.py` (a narrated, assertion-checked walkthrough of every feature)
plus `demo.sh` (runs both of the above, a full wallet-CLI session, and a
live HTTP spin-up of the explorer, end to end). See `REVIEW.md` for the
adversarial pass: 7 real bugs found and fixed, including two — gossip
silently never being delivered, and difficulty drifting easier forever —
that only surfaced by actually *running* the shipped server for several
minutes, not by reading the code or trusting the pre-existing test suite.

## Where a human could take this next

- **Real networking.** Swap `SimNetwork`'s in-process discrete-event queue
  for actual sockets (asyncio + a length-prefixed framing of the existing
  `serialize()`/`deserialize()` wire format) and run genuinely separate
  processes/machines instead of one process simulating several nodes.
- **A script system.** Right now every output is a single
  pubkey-hash-locked address (P2PKH-only). Adding even a minimal script
  interpreter (OP_CHECKSIG, OP_CHECKMULTISIG, timelocks) would unlock
  multisig wallets, payment channels, and eventually something
  Lightning-shaped.
- **Incremental UTXO diffs instead of full-chain replay.** `blockchain.py`
  deliberately replays a candidate branch from genesis for simplicity
  (documented trade-off, fine at this project's demo scale); a real node
  keeps per-block undo logs so a reorg costs O(reorg depth), not
  O(chain height).
- **Compact-bits difficulty encoding** instead of a raw 256-bit integer
  target, if wire-format compactness ever mattered here.
- **A real block-sync protocol** (getheaders/getdata) instead of
  `Node.announce_chain()`'s "just re-broadcast everything" stand-in for
  post-partition resync.
- **SPV / light clients**, using the Merkle-proof machinery that's
  already built — a client that trusts headers-only and asks a full node
  for inclusion proofs on demand.
