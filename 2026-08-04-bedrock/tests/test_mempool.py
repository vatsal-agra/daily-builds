import unittest

from bedrock.chain import COIN
from bedrock.mempool import MempoolError
from bedrock.node import Node
from bedrock.wallet import Wallet


class TestMempool(unittest.TestCase):
    def setUp(self):
        self.node = Node()
        self.alice = Wallet.generate()
        self.bob = Wallet.generate()
        self.node.mine_block(self.alice.address)

    def test_valid_transaction_accepted(self):
        tx = self.alice.build_transaction(self.node.chain, self.bob.address, 1 * COIN, fee=100)
        self.assertTrue(self.node.mempool.add_transaction(tx, self.node.chain))
        self.assertIn(tx.txid, self.node.mempool)

    def test_duplicate_submission_returns_false_not_error(self):
        tx = self.alice.build_transaction(self.node.chain, self.bob.address, 1 * COIN, fee=100)
        self.node.mempool.add_transaction(tx, self.node.chain)
        self.assertFalse(self.node.mempool.add_transaction(tx, self.node.chain))

    def test_coinbase_rejected_from_mempool(self):
        from bedrock.transaction import Transaction, TxOutput
        coinbase = Transaction(version=1, inputs=[], outputs=[TxOutput(1, self.alice.address)], coinbase_data=b"x")
        with self.assertRaises(MempoolError):
            self.node.mempool.add_transaction(coinbase, self.node.chain)

    def test_confirmed_transaction_drops_from_mempool_on_rebase(self):
        tx = self.alice.build_transaction(self.node.chain, self.bob.address, 1 * COIN, fee=100)
        self.node.mempool.add_transaction(tx, self.node.chain)
        self.node.mine_block(self.alice.address)  # mines it and rebases
        self.assertEqual(len(self.node.mempool), 0)
        self.assertNotIn(tx.txid, self.node.mempool)

    def test_drop_removes_reservation(self):
        tx = self.alice.build_transaction(self.node.chain, self.bob.address, 1 * COIN, fee=100)
        self.node.mempool.add_transaction(tx, self.node.chain)
        self.node.mempool.drop(tx.txid)
        self.assertEqual(len(self.node.mempool.reserved), 0)
        # the same tx (spending the same utxo) can be re-added after dropping
        self.assertTrue(self.node.mempool.add_transaction(tx, self.node.chain))


if __name__ == "__main__":
    unittest.main()
