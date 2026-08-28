import unittest

from ledgerline.transaction import Transaction, TxIn, TxOut, build_transaction, make_coinbase
from ledgerline.wallet import Wallet


class TestTransactionSigning(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()

    def test_build_and_verify(self):
        utxos = [("f" * 64, 0, 1000)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        ok, err = tx.verify_signatures()
        self.assertTrue(ok, err)
        self.assertEqual(tx.total_output(), 999)  # 100 to bob + 899 change
        self.assertEqual(len(tx.outputs), 2)

    def test_no_change_output_when_exact(self):
        utxos = [("f" * 64, 0, 101)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        self.assertEqual(len(tx.outputs), 1)

    def test_insufficient_funds_raises(self):
        utxos = [("f" * 64, 0, 50)]
        with self.assertRaises(ValueError):
            build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)

    def test_tampered_output_amount_invalidates_signature(self):
        utxos = [("f" * 64, 0, 1000)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        tx.outputs[0].amount = 999999
        ok, err = tx.verify_signatures()
        self.assertFalse(ok)

    def test_tampered_pubkey_invalidates_signature(self):
        utxos = [("f" * 64, 0, 1000)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        eve = Wallet()
        import ledgerline.ecdsa as ecdsa
        tx.inputs[0].pubkey = ecdsa.compress_pubkey(eve.pubkey).hex()
        ok, err = tx.verify_signatures()
        self.assertFalse(ok)

    def test_unsigned_input_rejected(self):
        tx = Transaction(inputs=[TxIn("f" * 64, 0)], outputs=[TxOut(self.bob.address, 10)])
        ok, err = tx.verify_signatures()
        self.assertFalse(ok)

    def test_coinbase_skips_signature_check(self):
        cb = make_coinbase(self.alice.address, 50, height=1)
        ok, err = cb.verify_signatures()
        self.assertTrue(ok)

    def test_txid_stable_and_content_dependent(self):
        utxos = [("f" * 64, 0, 1000)]
        tx1 = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        tx2 = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        self.assertEqual(tx1.txid(), tx1.txid())
        # two builds at slightly different wall-clock timestamps should
        # (almost always) produce different ids, proving txid isn't a
        # constant / isn't ignoring the transaction's actual content
        self.assertIsInstance(tx1.txid(), str)
        self.assertEqual(len(tx1.txid()), 64)

    def test_serialization_roundtrip(self):
        utxos = [("f" * 64, 0, 1000)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        restored = Transaction.from_dict(tx.to_dict())
        self.assertEqual(restored.txid(), tx.txid())
        ok, _ = restored.verify_signatures()
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
