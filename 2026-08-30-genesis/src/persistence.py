"""On-disk persistence for a single local node: a block store, a wallet
keypair, and a pending-transaction pool -- enough for `cli.py` to survive
being invoked as a fresh process on every command (a real wallet CLI has to
work that way; a chain and mempool that only live in one process's memory
would make `send` in one command and `mine` in the next command
impossible)."""
from __future__ import annotations

import json
import os
from typing import Optional, Tuple

import block as blk
import blockchain as bc
import crypto as c
import transaction as tx
from mempool import Mempool
from wallet import Wallet

CHAIN_FILE = "chain.dat"
WALLET_FILE = "wallet.json"
MEMPOOL_FILE = "mempool.dat"
FIXED_GENESIS_TIMESTAMP = 1_735_689_600  # 2025-01-01T00:00:00Z, arbitrary but fixed so every fresh
                                           # data directory starts from a byte-identical genesis block


def _write_varint(n: int) -> bytes:
    from transaction import _write_varint as w
    return w(n)


def make_fixed_genesis() -> blk.Block:
    burn_hash = b"\x00" * 20
    cb = tx.Transaction.coinbase(burn_hash, reward=bc.subsidy_at(0), height=0)
    g = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[cb],
                       target=bc.GENESIS_TARGET_DEFAULT, timestamp=FIXED_GENESIS_TIMESTAMP)
    g.mine()
    return g


def load_or_init_chain(data_dir: str) -> bc.Blockchain:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, CHAIN_FILE)
    if not os.path.exists(path):
        genesis = make_fixed_genesis()
        chain = bc.Blockchain(genesis)
        with open(path, "wb") as f:
            raw = genesis.serialize()
            f.write(_write_varint(len(raw)) + raw)
        return chain

    with open(path, "rb") as f:
        data = f.read()
    off = 0
    genesis, off = _read_one_block(data, off)
    chain = bc.Blockchain(genesis)
    while off < len(data):
        block, off = _read_one_block(data, off)
        result = chain.accept_block(block)
        if not result.accepted:
            raise bc.ChainError(f"corrupt or invalid chain file at block {block.block_hash_hex()[:10]}: {result.reason}")
    return chain


def _read_one_block(data: bytes, off: int) -> Tuple[blk.Block, int]:
    from transaction import _read_varint
    length, off = _read_varint(data, off)
    raw = data[off:off + length]
    block, _ = blk.Block.deserialize(raw)
    return block, off + length


def append_block(data_dir: str, block: blk.Block) -> None:
    path = os.path.join(data_dir, CHAIN_FILE)
    raw = block.serialize()
    with open(path, "ab") as f:
        f.write(_write_varint(len(raw)) + raw)


def load_or_init_wallet(data_dir: str) -> Wallet:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, WALLET_FILE)
    if not os.path.exists(path):
        w = Wallet()
        with open(path, "w") as f:
            json.dump({"private_key_hex": "%064x" % w.keypair.private_key}, f)
        return w
    with open(path) as f:
        obj = json.load(f)
    priv = int(obj["private_key_hex"], 16)
    return Wallet(c.KeyPair.from_private(priv))


def load_mempool(data_dir: str, chain: bc.Blockchain) -> Tuple[Mempool, list]:
    """Returns (mempool, dropped) where `dropped` is [(txid_prefix, reason), ...]
    for any persisted transaction that no longer validates (e.g. it was
    confirmed or double-spent by something that happened since it was
    saved) -- surfaced to the caller rather than silently discarded."""
    mp = Mempool()
    path = os.path.join(data_dir, MEMPOOL_FILE)
    if not os.path.exists(path):
        return mp, []
    with open(path, "rb") as f:
        data = f.read()
    from transaction import _read_varint
    off = 0
    utxo = chain.utxo_set()
    lookup = lambda txid, idx: utxo.get((txid, idx))
    dropped = []
    while off < len(data):
        length, off = _read_varint(data, off)
        raw = data[off:off + length]
        off += length
        t, _ = tx.Transaction.deserialize(raw)
        ok, reason = mp.add_transaction(t, lookup)
        if not ok:
            dropped.append((t.txid_hex()[:10], reason))
    return mp, dropped


def save_mempool(data_dir: str, mempool: Mempool) -> None:
    path = os.path.join(data_dir, MEMPOOL_FILE)
    with open(path, "wb") as f:
        for t in mempool.txs.values():
            raw = t.serialize()
            f.write(_write_varint(len(raw)) + raw)
