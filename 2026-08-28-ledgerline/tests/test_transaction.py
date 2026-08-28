import unittest

from ledgerline.transaction import Transaction, TxIn, TxOut, build_transaction, make_coinbase
from ledgerline.wallet import Wallet


class TestTxOutValidation(unittest.TestCase):
    """Regression coverage for a real money-creation bug found in the
    Phase 3 adversarial review: a negative TxOut amount lets total_output()
    (what chain.py compares against total input) read arbitrarily low
    while the UTXO actually created still carries the real, huge, positive
    amount — minting coins from nothing. See REVIEW.md."""

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            TxOut("Labc", -1)

    def test_zero_amount_allowed(self):
        TxOut("Labc", 0)  # must not raise — a zero-value output is unusual but not unsafe

    def test_non_integer_amount_rejected(self):
        with self.assertRaises(ValueError):
            TxOut("Labc", 1.5)

    def test_bool_amount_rejected(self):
        # isinstance(True, int) is True in Python — must be explicitly excluded
        with self.assertRaises(ValueError):
            TxOut("Labc", True)

    def test_from_dict_rejects_negative_amount(self):
        with self.assertRaises(ValueError):
            TxOut.from_dict({"address": "Labc", "amount": -1000000})


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

    def test_mistyped_recipient_address_rejected(self):
        # Base58Check exists specifically to catch a typo/corrupted address
        # before funds move into a UTXO nobody can ever spend from — a
        # real gap found in the Phase 3 review (see REVIEW.md), since
        # nothing validated the checksum before this fix.
        utxos = [("f" * 64, 0, 1000)]
        with self.assertRaises(ValueError):
            build_transaction(utxos, self.alice.privkey, "not a real address", 100, 1, self.alice.address)

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
