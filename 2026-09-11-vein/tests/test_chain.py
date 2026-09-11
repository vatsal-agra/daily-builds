import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vein.core.chain import Blockchain, ChainParams, make_coinbase, ValidationError, subsidy_at_height
from vein.core.block import Block, BlockHeader, target_to_bits, MAX_TARGET
from vein.core.transaction import Transaction, TxIn, TxOut, merkle_root
from vein.core.script import Script
from vein.core.mempool import Mempool
from vein.crypto.ecdsa import generate_privkey
from vein.crypto.curve import derive_pubkey
from vein.crypto.address import serialize_pubkey
from vein.crypto.hashes import hash160


def mine(header: BlockHeader, max_tries=50_000_000) -> BlockHeader:
    target = header.target()
    n = 0
    while True:
        header.nonce = n & 0xFFFFFFFF
        if int.from_bytes(header.hash(), "big") <= target:
            return header
        n += 1
        if n > max_tries:
            raise RuntimeError("mining did not converge")


def easy_params(**overrides):
    defaults = dict(initial_bits=target_to_bits(MAX_TARGET >> 6), retarget_interval=1000)
    defaults.update(overrides)
    return ChainParams(**defaults)


def mine_block(chain, t, txs, pkh, extra_nonce, prev=None):
    prev = prev or chain.tip_hash
    parent_height = chain.meta[prev].height
    cb = make_coinbase(parent_height + 1, 5_000_000_000, pkh, extra_nonce=extra_nonce)
    all_txs = [cb] + txs
    bits = chain.expected_bits_after(prev)
    header = BlockHeader(1, prev, merkle_root([tx.txid() for tx in all_txs]), t, bits, 0)
    mine(header)
    return Block(header, all_txs)


def mine_standalone_chain(params, genesis_hash, genesis_timestamp, n, pkh):
    """Build a chain of `n` blocks purely from local Python objects — no
    chain.meta lookups — for tests that must construct blocks *before*
    submitting any of them (e.g. to feed a node deliberately out of order).
    Assumes bits stay constant (retarget_interval bigger than `n`).
    """
    blocks = []
    prev_hash = genesis_hash
    prev_ts = genesis_timestamp
    for i in range(1, n + 1):
        cb = make_coinbase(i, subsidy_at_height(i, params), pkh, extra_nonce=i)
        header = BlockHeader(1, prev_hash, merkle_root([cb.txid()]), prev_ts + i, params.initial_bits, 0)
        mine(header)
        blk = Block(header, [cb])
        blocks.append(blk)
        prev_hash = blk.hash()
    return blocks


def keypair():
    priv = generate_privkey()
    pub = serialize_pubkey(derive_pubkey(priv))
    return priv, pub, hash160(pub)


class TestGenesisAndMining(unittest.TestCase):
    def test_genesis_meets_its_own_pow(self):
        chain = Blockchain(easy_params())
        self.assertTrue(chain.blocks[chain.tip_hash].header.meets_target())
        self.assertEqual(chain.height, 0)

    def test_mine_and_track_coinbase_balance(self):
        chain = Blockchain(easy_params())
        _, _, pkh = keypair()
        t = int(time.time())
        for i in range(1, 4):
            blk = mine_block(chain, t + i, [], pkh, i)
            self.assertTrue(chain.add_block(blk, now=t + i + 1))
        self.assertEqual(chain.height, 3)
        self.assertEqual(chain.balance_of(pkh), 5_000_000_000 * 3)

    def test_rejects_bad_pow(self):
        chain = Blockchain(easy_params())
        priv, pub, pkh = keypair()
        t = int(time.time())
        cb = make_coinbase(1, 5_000_000_000, pkh, 1)
        bits = chain.expected_bits_after(chain.tip_hash)
        header = BlockHeader(1, chain.tip_hash, merkle_root([cb.txid()]), t + 1, bits, 0)
        header.nonce = 0  # almost certainly does not satisfy target, no mining performed
        blk = Block(header, [cb])
        if header.meets_target():
            self.skipTest("nonce 0 accidentally satisfied target")
        with self.assertRaises(ValidationError):
            chain.add_block(blk, now=t + 2)

    def test_rejects_bad_merkle_root(self):
        chain = Blockchain(easy_params())
        _, _, pkh = keypair()
        blk = mine_block(chain, int(time.time()) + 1, [], pkh, 1)
        blk.header.merkle_root = os.urandom(32)
        with self.assertRaises(ValidationError):
            chain.add_block(blk)

    def test_rejects_non_advancing_timestamp(self):
        chain = Blockchain(easy_params())
        _, _, pkh = keypair()
        genesis_ts = chain.blocks[chain.tip_hash].header.timestamp
        blk = mine_block(chain, genesis_ts, [], pkh, 1)  # not > parent
        with self.assertRaises(ValidationError):
            chain.add_block(blk)

    def test_rejects_wrong_difficulty_bits(self):
        chain = Blockchain(easy_params())
        _, _, pkh = keypair()
        blk = mine_block(chain, int(time.time()) + 1, [], pkh, 1)
        blk.header.bits = target_to_bits(MAX_TARGET >> 2)  # wrong, doesn't match expected
        # re-mine so it still satisfies (now-wrong) target, isolating the bits-mismatch check
        mine(blk.header)
        with self.assertRaises(ValidationError):
            chain.add_block(blk)


class TestReorgAndDoubleSpend(unittest.TestCase):
    def test_fork_resolves_by_cumulative_work_and_rolls_back_utxo(self):
        chain = Blockchain(easy_params())
        privA, pubA, pkhA = keypair()
        privB, pubB, pkhB = keypair()
        privM, pubM, pkhM = keypair()
        t = int(time.time())

        b1 = mine_block(chain, t + 1, [], pkhM, 1)
        self.assertTrue(chain.add_block(b1, now=t + 2))
        funding_txid = b1.transactions[0].txid()
        funding_out = b1.transactions[0].outputs[0]

        spendA = Transaction(inputs=[TxIn(funding_txid, 0, Script([]))],
                              outputs=[TxOut(4_999_990_000, Script.p2pkh_lock(pkhA))])
        spendA.sign_input(0, privM, funding_out.script_pubkey, pubM)
        spendB = Transaction(inputs=[TxIn(funding_txid, 0, Script([]))],
                              outputs=[TxOut(4_999_990_000, Script.p2pkh_lock(pkhB))])
        spendB.sign_input(0, privM, funding_out.script_pubkey, pubM)
        self.assertNotEqual(spendA.txid(), spendB.txid())

        blkA = mine_block(chain, t + 3, [spendA], pkhM, 2, prev=b1.hash())
        self.assertTrue(chain.add_block(blkA, now=t + 4))
        self.assertEqual(chain.balance_of(pkhA), 4_999_990_000)
        height_after_a = chain.height

        blkB1 = mine_block(chain, t + 3, [spendB], pkhM, 3, prev=b1.hash())
        self.assertFalse(chain.add_block(blkB1, now=t + 5))  # equal work, no reorg yet
        self.assertEqual(chain.tip_hash, blkA.hash())

        blkB2 = mine_block(chain, t + 5, [], pkhM, 4, prev=blkB1.hash())
        self.assertTrue(chain.add_block(blkB2, now=t + 6))  # now strictly more work -> reorg
        self.assertEqual(chain.tip_hash, blkB2.hash())
        self.assertEqual(chain.height, height_after_a + 1)

        self.assertEqual(chain.balance_of(pkhA), 0, "losing fork's spend must be rolled back")
        self.assertEqual(chain.balance_of(pkhB), 4_999_990_000, "winning fork's spend must be confirmed")

    def test_utxo_set_matches_replay_after_reorg(self):
        """The live UTXO set after a reorg must equal a from-scratch
        replay of the winning chain — not just 'balances look right'."""
        chain = Blockchain(easy_params())
        _, _, pkhM = keypair()
        t = int(time.time())
        b1 = mine_block(chain, t + 1, [], pkhM, 1)
        chain.add_block(b1, now=t + 2)
        bA = mine_block(chain, t + 2, [], pkhM, 2, prev=b1.hash())
        chain.add_block(bA, now=t + 3)

        bB1 = mine_block(chain, t + 2, [], pkhM, 3, prev=b1.hash())
        chain.add_block(bB1, now=t + 4)
        bB2 = mine_block(chain, t + 3, [], pkhM, 4, prev=bB1.hash())
        chain.add_block(bB2, now=t + 5)  # reorg onto B

        replay = chain._replay_utxo_at(chain.tip_hash)
        self.assertEqual(set(replay.keys()), set(chain.utxo.coins.keys()))
        for k in replay:
            self.assertEqual(replay[k].value, chain.utxo.coins[k].value)


class TestOrphanHandling(unittest.TestCase):
    def test_out_of_order_blocks_get_applied_once_parent_arrives(self):
        params = easy_params()
        chain = Blockchain(params)
        _, _, pkhM = keypair()
        genesis = chain.blocks[chain.tip_hash].header
        b1, b2, b3 = mine_standalone_chain(params, chain.tip_hash, genesis.timestamp, 3, pkhM)
        t = genesis.timestamp

        # Deliver in reverse order: b3, b2 should buffer as orphans; only
        # once b1 arrives should the whole cascade apply.
        self.assertFalse(chain.add_block(b3, now=t + 4))
        self.assertEqual(chain.height, 0)
        self.assertFalse(chain.add_block(b2, now=t + 4))
        self.assertEqual(chain.height, 0)
        self.assertTrue(chain.add_block(b1, now=t + 4))
        self.assertEqual(chain.height, 3)
        self.assertEqual(chain.tip_hash, b3.hash())

    def test_long_orphan_cascade_does_not_recurse_deeply(self):
        """A hostile peer relaying hundreds of blocks in reverse order
        must not blow the Python recursion limit."""
        params = easy_params(retarget_interval=10_000)
        chain = Blockchain(params)
        _, _, pkhM = keypair()
        genesis = chain.blocks[chain.tip_hash].header
        blocks = mine_standalone_chain(params, chain.tip_hash, genesis.timestamp, 300, pkhM)

        now = genesis.timestamp + 1000
        for blk in reversed(blocks[1:]):  # everything except the first, all orphaned
            chain.add_block(blk, now=now)
        self.assertEqual(chain.height, 0)
        chain.add_block(blocks[0], now=now)  # triggers the whole cascade
        self.assertEqual(chain.height, 300)
        self.assertEqual(chain.tip_hash, blocks[-1].hash())


class TestMempoolIntegration(unittest.TestCase):
    def test_reject_empty_transaction(self):
        chain = Blockchain(easy_params())
        mp = Mempool(chain)
        empty = Transaction(inputs=[], outputs=[])
        with self.assertRaises(ValidationError):
            mp.add_transaction(empty)

    def test_reject_tx_spending_same_input_twice(self):
        chain = Blockchain(easy_params())
        mp = Mempool(chain)
        priv, pub, pkh = keypair()
        t = int(time.time())
        b1 = mine_block(chain, t + 1, [], pkh, 1)
        chain.add_block(b1, now=t + 2)
        cb = b1.transactions[0]
        prevout = cb.outputs[0]

        tx = Transaction(
            inputs=[TxIn(cb.txid(), 0, Script([])), TxIn(cb.txid(), 0, Script([]))],
            outputs=[TxOut(1000, Script.p2pkh_lock(pkh))],
        )
        tx.sign_input(0, priv, prevout.script_pubkey, pub)
        tx.sign_input(1, priv, prevout.script_pubkey, pub)
        with self.assertRaises(ValidationError):
            mp.add_transaction(tx)

    def test_mempool_revalidate_drops_tx_orphaned_by_reorg(self):
        """A mempool tx that spends a coin which only ever existed on a
        branch that later loses a reorg must be dropped by revalidate() —
        not because it conflicts with anything, but because the coin it
        spends never existed on the winning chain at all.
        """
        chain = Blockchain(easy_params())
        mp = Mempool(chain)
        priv, pub, pkh = keypair()
        privC, _, pkhC = keypair()
        t = int(time.time())

        b1 = mine_block(chain, t + 1, [], pkh, 1)
        chain.add_block(b1, now=t + 2)

        # blkA becomes the active tip (direct extension) — its own
        # coinbase output now exists in the live UTXO set.
        blkA = mine_block(chain, t + 2, [], pkh, 2, prev=b1.hash())
        chain.add_block(blkA, now=t + 3)
        blkA_coinbase = blkA.transactions[0]

        spendC = Transaction(inputs=[TxIn(blkA_coinbase.txid(), 0, Script([]))],
                              outputs=[TxOut(4_999_990_000, Script.p2pkh_lock(pkhC))])
        spendC.sign_input(0, priv, blkA_coinbase.outputs[0].script_pubkey, pub)
        self.assertTrue(mp.add_transaction(spendC))  # valid right now: blkA is active

        # A competing branch off b1 that ends up with more cumulative
        # work reorgs blkA out of the active chain entirely.
        blkB1 = mine_block(chain, t + 2, [], pkh, 3, prev=b1.hash())
        chain.add_block(blkB1, now=t + 4)
        blkB2 = mine_block(chain, t + 3, [], pkh, 4, prev=blkB1.hash())
        chain.add_block(blkB2, now=t + 5)  # reorg away from blkA

        self.assertNotEqual(chain.tip_hash, blkA.hash())
        self.assertIsNone(chain.utxo.get(blkA_coinbase.txid(), 0), "blkA's coinbase must not survive the reorg")

        dropped = mp.revalidate()
        self.assertIn(spendC.txid(), dropped, "a tx spending an orphaned coinbase must not linger")
        self.assertEqual(len(mp), 0)


class TestMempoolFeeRateSelection(unittest.TestCase):
    def test_select_for_block_orders_by_fee_rate_not_flat_fee(self):
        chain = Blockchain(easy_params())
        mp = Mempool(chain)
        priv, pub, pkh = keypair()
        t = int(time.time())
        b1 = mine_block(chain, t + 1, [], pkh, 1)
        chain.add_block(b1, now=t + 2)
        cb = b1.transactions[0]
        prevout = cb.outputs[0]

        # tx1: one big output (large tx, low flat fee -> low fee rate)
        many_outs = [TxOut(1, Script.p2pkh_lock(pkh)) for _ in range(80)]
        tx_big = Transaction(inputs=[TxIn(cb.txid(), 0, Script([]))],
                              outputs=many_outs + [TxOut(cb.outputs[0].value - 80 - 500, Script.p2pkh_lock(pkh))])
        tx_big.sign_input(0, priv, prevout.script_pubkey, pub)

        # tx2 spends a *different* coin: small tx, smaller flat fee, but far higher fee rate
        b2 = mine_block(chain, t + 2, [], pkh, 2, prev=b1.hash())
        chain.add_block(b2, now=t + 3)
        cb2 = b2.transactions[0]
        tx_small = Transaction(inputs=[TxIn(cb2.txid(), 0, Script([]))],
                                outputs=[TxOut(cb2.outputs[0].value - 400, Script.p2pkh_lock(pkh))])
        tx_small.sign_input(0, priv, cb2.outputs[0].script_pubkey, pub)

        mp.add_transaction(tx_big)
        mp.add_transaction(tx_small)

        big_fee = mp.entries[tx_big.txid()].fee
        small_fee = mp.entries[tx_small.txid()].fee
        self.assertGreater(big_fee, small_fee, "test setup: big tx should pay the larger flat fee")

        selected = mp.select_for_block()
        self.assertEqual(selected[0].txid(), tx_small.txid(),
                          "the far-higher fee-*rate* tx should be selected first despite its smaller flat fee")


if __name__ == "__main__":
    unittest.main()
