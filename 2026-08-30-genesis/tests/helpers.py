import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import block as blk
import blockchain as bc
import transaction as tx


def make_genesis(timestamp=1_000_000, target=None):
    burn_hash = b"\x00" * 20
    cb = tx.Transaction.coinbase(burn_hash, reward=bc.subsidy_at(0), height=0)
    g = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[cb],
                       target=target or bc.GENESIS_TARGET_DEFAULT, timestamp=timestamp)
    g.mine()
    return g


def mine_on_top(chain, prev_hash, txs, timestamp, target=None):
    t = target if target is not None else chain._expected_target(prev_hash)
    b = blk.Block.new(prev_hash=prev_hash, transactions=txs, target=t, timestamp=timestamp)
    nonce = b.mine()
    assert nonce is not None, "failed to mine test block within nonce budget"
    return b
