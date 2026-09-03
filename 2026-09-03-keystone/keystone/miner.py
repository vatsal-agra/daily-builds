"""Assemble a block template from the mempool + a coinbase reward, then run
the real PoW search over it."""
from __future__ import annotations

import time

from . import pow as pow_module
from .block import Block, BlockHeader
from .transaction import make_coinbase
from .wallet import Wallet


def assemble_template(chain, mempool, miner_wallet: Wallet, extra_nonce: int, max_txs: int = 50) -> Block:
    tip_hash = chain.tip_hash
    height = chain.heights[tip_hash] + 1
    selected = mempool.select_for_block(max_txs)
    total_fees = sum(mempool.fees[tx.txid()] for tx in selected)
    reward = chain.block_reward_at(height) + total_fees

    coinbase = make_coinbase(miner_wallet.lock_script_for_self(), reward, height=height, extra_nonce=extra_nonce)
    transactions = [coinbase] + selected

    bits = chain.compute_next_bits(tip_hash)
    header = BlockHeader(
        version=1,
        prev_hash=tip_hash,
        merkle_root="",
        timestamp=time.time(),
        bits=bits,
        nonce=0,
    )
    block = Block(header=header, transactions=transactions, height=height)
    block.header.merkle_root = block.compute_merkle_root()
    return block


def mine_block(chain, mempool, miner_wallet: Wallet, extra_nonce: int = 0, max_nonce: int = 1 << 32,
                should_stop=None):
    """Assemble a template and search for a valid nonce. Returns a mined
    Block (not yet added to the chain — caller decides what to do with it),
    or None if should_stop fired or max_nonce was exhausted first."""
    block = assemble_template(chain, mempool, miner_wallet, extra_nonce)

    def prefix_fn(nonce):
        block.header.nonce = nonce
        return block.header.bytes_for_hash()

    result = pow_module.mine(prefix_fn, block.header.bits, max_nonce=max_nonce, should_stop=should_stop)
    if result is None:
        return None
    nonce, _h = result
    block.header.nonce = nonce
    return block
