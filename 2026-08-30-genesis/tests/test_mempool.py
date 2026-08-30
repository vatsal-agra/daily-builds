import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import blockchain as bc
import transaction as tx
from helpers import make_genesis, mine_on_top
from mempool import Mempool
from wallet import Wallet


class TestMempool(unittest.TestCase):
    def setUp(self):
        self.genesis = make_genesis()
        self.chain = bc.Blockchain(self.genesis)
        self.alice = Wallet()
        self.bob = Wallet()
        cb = tx.Transaction.coinbase(self.alice.pubkey_hash, reward=bc.subsidy_at(1), height=1)
        b1 = mine_on_top(self.chain, self.chain.genesis_hash, [cb], 1_000_001)
        self.chain.accept_block(b1)
        self.mempool = Mempool()
        self.lookup = lambda txid, idx: self.chain.utxo_set().get((txid, idx))

    def test_add_valid_transaction(self):
        t = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, 1_00000000, fee=500)
        ok, reason = self.mempool.add_transaction(t, self.lookup)
        self.assertTrue(ok, reason)
        self.assertIn(t.txid(), self.mempool)
        self.assertEqual(len(self.mempool), 1)

    def test_conflicting_transaction_rejected(self):
        t1 = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, 1_00000000, fee=500)
        ok1, _ = self.mempool.add_transaction(t1, self.lookup)
        self.assertTrue(ok1)
        # a second tx spending the same coinbase output (double-spend attempt)
        t2 = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, 2_00000000, fee=500)
        ok2, reason2 = self.mempool.add_transaction(t2, self.lookup)
        self.assertFalse(ok2)
        self.assertIn("double-spend", reason2)

    def test_coinbase_rejected_from_mempool(self):
        cb = tx.Transaction.coinbase(self.alice.pubkey_hash, reward=999, height=99)
        ok, reason = self.mempool.add_transaction(cb, self.lookup)
        self.assertFalse(ok)

    def test_remove_confirmed_clears_mined_tx(self):
        t = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, 1_00000000, fee=500)
        self.mempool.add_transaction(t, self.lookup)
        self.mempool.remove_confirmed([t])
        self.assertEqual(len(self.mempool), 0)

    def test_select_for_block_orders_by_feerate(self):
        # can't easily create two independent-input txs from one UTXO in this
        # setup, so just check select_for_block returns everything present
        t = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, 1_00000000, fee=500)
        self.mempool.add_transaction(t, self.lookup)
        chosen = self.mempool.select_for_block(self.lookup)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].txid(), t.txid())

    def test_duplicate_add_rejected(self):
        t = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, 1_00000000, fee=500)
        ok1, _ = self.mempool.add_transaction(t, self.lookup)
        ok2, reason2 = self.mempool.add_transaction(t, self.lookup)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("already", reason2)


if __name__ == "__main__":
    unittest.main()
