# Keystone

A from-scratch proof-of-work blockchain & cryptocurrency: secp256k1 wallets,
UTXO transactions, Merkle-committed blocks, difficulty-retargeting mining,
full chain validation, and a real gossiping P2P network of independent
nodes over TCP sockets.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
plus both stretch features (block explorer, m-of-n multisig scripting) work
end-to-end. 9 real bugs found via hostile testing — including a critical
difficulty-retarget cliff that was silently stalling the whole network at
the first retarget boundary in ~40-60% of runs, and a `SyntaxError` in the
explorer that meant it had never actually been run before Phase 4 — are
found, root-caused, and fixed. See [PLAN.md](PLAN.md) for architecture and
[REVIEW.md](REVIEW.md) for the full findings writeup.

## Try it

```
python3 -m keystone keygen                                   # a wallet
python3 -m keystone demo --nodes 4 --seconds 8                # the full network demo
python3 -m keystone explorer --nodes 3 --seconds 20 --port 8080  # live block explorer UI
python3 -m keystone script-demo                               # 2-of-3 multisig demo
```

## Quick look

```
$ python3 -m keystone demo --nodes 4 --seconds 8
Starting a 4-node Keystone network (ring topology, real TCP sockets)...
Mining for 8.0s across all 4 nodes...
  [demo payment] node2 -> wallet3: 4999999000 keystones

=== Demo report ===
  node0: height=9 tip=0000e9ca17cd7fdf… blocks_mined=1 peers=2
  ...
  converged on one tip: True
  wallet-to-wallet payment confirmed on-chain: True
  wallet0 (...) balance per node: [15000000000, 15000000000, 15000000000, 15000000000]
  ...
RESULT: PASS
```

Every node above is an independent `Blockchain` + `Mempool` + `Node`
talking to its neighbors over real `socket.socket` TCP connections — not
one shared in-process object.

## What's implemented so far

- `keystone/crypto.py` — secp256k1 point arithmetic, RFC-6979 deterministic
  ECDSA sign/verify, RIPEMD-160 from scratch, base58check.
- `keystone/wallet.py`, `script.py` — keypairs/addresses, a small stack-based
  scripting VM (P2PKH + m-of-n multisig).
- `keystone/transaction.py`, `merkle.py`, `block.py` — UTXO transactions,
  Merkle trees with inclusion proofs, blocks.
- `keystone/pow.py`, `miner.py` — compact-bits PoW targets, a real mining
  search, Bitcoin-style difficulty retargeting.
- `keystone/utxo.py`, `mempool.py`, `chain.py` — full UTXO-set validation
  (double-spend/script/coinbase-maturity checks), mempool, and a
  `Blockchain` that resolves forks by cumulative work with real reorgs and
  an orphan-block pool.
- `keystone/wire.py`, `network.py`, `node.py` — an INV/GETDATA gossip
  protocol over real TCP sockets, wired into a runnable `FullNode`.
- `keystone/explorer.py` — a stdlib-`http.server` block explorer (stretch).
- `keystone/cli.py` — the `keystone` CLI (`keygen`, `demo`, `explorer`,
  `script-demo`).

Next: adversarial review (Phase 3), stretch polish (Phase 4), full test
suite (Phase 5), final writeup (Phase 6).
