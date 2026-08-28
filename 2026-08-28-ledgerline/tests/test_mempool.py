import unittest

from ledgerline.mempool import Mempool
from ledgerline.transaction import build_transaction
from ledgerline.wallet import Wallet


class TestMempool(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()
        self.carol = Wallet()

    def _tx(self, prev_txid, amount, fee, recipient=None):
        utxos = [(prev_txid, 0, amount + fee)]
        return build_transaction(utxos, self.alice.privkey, recipient or self.bob.address, amount, fee, self.alice.address)

    def test_selects_highest_fee_first(self):
        mp = Mempool()
        tx_low = self._tx("a" * 64, 10, 1)
        tx_high = self._tx("b" * 64, 10, 5)
        mp.add(tx_low, 1)
        mp.add(tx_high, 5)
        selected = mp.select_for_block()
        self.assertEqual(selected[0].txid(), tx_high.txid())

    def test_max_count_zero_returns_nothing(self):
        mp = Mempool()
        tx = self._tx("a" * 64, 10, 1)
        mp.add(tx, 1)
        self.assertEqual(mp.select_for_block(max_count=0), [])

    def test_negative_max_count_returns_nothing(self):
        mp = Mempool()
        tx = self._tx("a" * 64, 10, 1)
        mp.add(tx, 1)
        self.assertEqual(mp.select_for_block(max_count=-5), [])

    def test_max_count_limits_selection(self):
        mp = Mempool()
        for i in range(5):
            tx = self._tx(f"{i}" * 64, 10, i)
            mp.add(tx, i)
        self.assertEqual(len(mp.select_for_block(max_count=2)), 2)

    def test_conflicting_inputs_only_one_selected(self):
        mp = Mempool()
        prev = "c" * 64
        tx1 = self._tx(prev, 10, 5, recipient=self.bob.address)
        tx2 = self._tx(prev, 20, 3, recipient=self.carol.address)
        mp.add(tx1, 5)
        mp.add(tx2, 3)
        selected = mp.select_for_block()
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].txid(), tx1.txid())  # higher fee wins the slot

    def test_remove_and_contains(self):
        mp = Mempool()
        tx = self._tx("a" * 64, 10, 1)
        mp.add(tx, 1)
        self.assertTrue(mp.contains(tx.txid()))
        mp.remove(tx.txid())
        self.assertFalse(mp.contains(tx.txid()))
        mp.remove(tx.txid())  # removing again must not raise

    def test_snapshot_shape(self):
        mp = Mempool()
        tx = self._tx("a" * 64, 10, 3)
        mp.add(tx, 3)
        snap = mp.snapshot()
        self.assertEqual(snap, [(tx.txid(), 3, len(tx.outputs))])


if __name__ == "__main__":
    unittest.main()
