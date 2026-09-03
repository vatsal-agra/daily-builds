import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone.block import Block, BlockHeader
from keystone.mempool import Mempool
from keystone.transaction import make_coinbase
from keystone.utxo import UTXOSet, ValidationError, COINBASE_MATURITY
from keystone.wallet import Wallet


def make_block(transactions, height, prev_hash="0" * 64):
    header = BlockHeader(version=1, prev_hash=prev_hash, merkle_root="", timestamp=height, bits=0, nonce=0)
    blk = Block(header=header, transactions=transactions, height=height)
    blk.header.merkle_root = blk.compute_merkle_root()
    return blk


class TestMempool(unittest.TestCase):
    def setUp(self):
        self.utxo = UTXOSet()
        self.alice = Wallet.generate()
        self.bob = Wallet.generate()
        self.eve = Wallet.generate()
        cb = make_coinbase(self.alice.lock_script_for_self(), 5000, height=0, extra_nonce=0)
        blk = make_block([cb], height=0)
        self.utxo.validate_and_apply_block(blk, block_reward=5000)
        self.spend_ref = (cb.txid(), 0)
        self.mempool = Mempool()

    def test_valid_tx_accepted(self):
        tx = self.alice.build_transaction([self.spend_ref], [(4000, self.bob.pubkey_hash)])
        self.assertTrue(self.mempool.try_add(tx, self.utxo, current_height=COINBASE_MATURITY))
        self.assertEqual(len(self.mempool), 1)
        self.assertIn(tx.txid(), self.mempool)

    def test_conflicting_tx_rejected(self):
        tx1 = self.alice.build_transaction([self.spend_ref], [(4000, self.bob.pubkey_hash)])
        tx2 = self.alice.build_transaction([self.spend_ref], [(4000, self.eve.pubkey_hash)])
        self.mempool.try_add(tx1, self.utxo, COINBASE_MATURITY)
        with self.assertRaises(ValidationError):
            self.mempool.try_add(tx2, self.utxo, COINBASE_MATURITY)

    def test_readding_same_tx_is_a_noop_not_error(self):
        tx = self.alice.build_transaction([self.spend_ref], [(4000, self.bob.pubkey_hash)])
        self.assertTrue(self.mempool.try_add(tx, self.utxo, COINBASE_MATURITY))
        self.assertFalse(self.mempool.try_add(tx, self.utxo, COINBASE_MATURITY))
        self.assertEqual(len(self.mempool), 1)

    def test_coinbase_rejected_from_mempool(self):
        cb = make_coinbase(self.bob.lock_script_for_self(), 5000, height=1, extra_nonce=0)
        with self.assertRaises(ValidationError):
            self.mempool.try_add(cb, self.utxo, COINBASE_MATURITY)

    def test_remove_confirmed(self):
        tx = self.alice.build_transaction([self.spend_ref], [(4000, self.bob.pubkey_hash)])
        self.mempool.try_add(tx, self.utxo, COINBASE_MATURITY)
        blk = make_block([make_coinbase(self.bob.lock_script_for_self(), 5000, 1, 0), tx], height=1)
        self.mempool.remove_confirmed(blk)
        self.assertEqual(len(self.mempool), 0)

    def test_select_for_block_orders_by_fee(self):
        # two independent, non-conflicting spends with different fees
        cb2 = make_coinbase(self.bob.lock_script_for_self(), 5000, height=0, extra_nonce=1)
        blk2 = make_block([cb2], height=0)
        # apply directly against a fresh coexisting output so it doesn't
        # conflict with self.spend_ref
        self.utxo.utxos[(cb2.txid(), 0)] = (cb2.outputs[0], 0, True)
        # bump height enough for both coinbases to be mature
        low_fee = self.alice.build_transaction([self.spend_ref], [(4999, self.bob.pubkey_hash)])  # fee=1
        high_fee = self.bob.build_transaction([(cb2.txid(), 0)], [(1000, self.eve.pubkey_hash)])  # fee=4000
        self.mempool.try_add(low_fee, self.utxo, COINBASE_MATURITY)
        self.mempool.try_add(high_fee, self.utxo, COINBASE_MATURITY)
        ordered = self.mempool.select_for_block()
        self.assertEqual(ordered[0].txid(), high_fee.txid())

    def test_readd_if_valid_returns_false_when_now_invalid(self):
        tx = self.alice.build_transaction([self.spend_ref], [(4000, self.bob.pubkey_hash)])
        # simulate: the referenced output no longer exists (already spent
        # on the now-winning chain)
        del self.utxo.utxos[self.spend_ref]
        self.assertFalse(self.mempool.readd_if_valid(tx, self.utxo, COINBASE_MATURITY))


if __name__ == "__main__":
    unittest.main()
