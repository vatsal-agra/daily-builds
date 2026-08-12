import copy
import unittest

from nonce.wallet import Wallet
from nonce.core.transaction import Transaction, TxIn, TxOut, pubkey_to_address, address_to_pkh


class TestTransaction(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()

    def _simple_tx(self):
        tx = Transaction([TxIn(b"\x11" * 32, 0)], [TxOut(1000, self.bob.address)])
        tx.sign_input(0, self.alice.privkey)
        return tx

    def test_sign_then_verify(self):
        tx = self._simple_tx()
        self.assertTrue(tx.verify_signatures())

    def test_txid_not_cached_stale_after_mutation(self):
        # regression test for REVIEW.md finding #1: mutating a Transaction
        # after computing txid() once must NOT return the old id.
        tx = self._simple_tx()
        original_txid = tx.txid()
        tx.outputs[0].amount += 1
        self.assertNotEqual(tx.txid(), original_txid, "txid() must reflect current state, not a stale cache")

    def test_txid_changes_with_signature(self):
        tx1 = self._simple_tx()
        tx2 = Transaction([TxIn(b"\x11" * 32, 0)], [TxOut(1000, self.bob.address)])
        tx2.sign_input(0, self.bob.privkey)  # different signer -> different signature
        self.assertNotEqual(tx1.txid(), tx2.txid())

    def test_wire_round_trip_preserves_txid(self):
        tx = self._simple_tx()
        txid_before = tx.txid()
        restored = Transaction.from_dict(tx.to_dict())
        self.assertEqual(restored.txid(), txid_before)
        self.assertTrue(restored.verify_signatures())

    def test_deepcopy_preserves_txid(self):
        tx = self._simple_tx()
        txid_before = tx.txid()
        cloned = copy.deepcopy(tx)
        self.assertEqual(cloned.txid(), txid_before)

    def test_unsigned_transaction_fails_verification(self):
        tx = Transaction([TxIn(b"\x11" * 32, 0)], [TxOut(1000, self.bob.address)])
        self.assertFalse(tx.verify_signatures())

    def test_coinbase_detection(self):
        cb = Transaction.coinbase(self.alice.address, 5_000_000_000)
        self.assertTrue(cb.is_coinbase())
        self.assertTrue(cb.verify_signatures())  # coinbase always "verifies" (no signature needed)
        self.assertFalse(self._simple_tx().is_coinbase())

    def test_negative_output_amount_rejected(self):
        with self.assertRaises(ValueError):
            TxOut(-1, self.alice.address)


class TestAddress(unittest.TestCase):
    def test_address_round_trips_to_pkh(self):
        w = Wallet()
        pkh = address_to_pkh(w.address)
        self.assertEqual(len(pkh), 20)

    def test_pubkey_to_address_deterministic(self):
        w = Wallet()
        self.assertEqual(pubkey_to_address(w.pubkey_bytes), w.address)

    def test_different_pubkeys_different_addresses(self):
        a, b = Wallet(), Wallet()
        self.assertNotEqual(a.address, b.address)

    def test_garbage_address_rejected(self):
        with self.assertRaises(ValueError):
            address_to_pkh("notAnAddress")


if __name__ == "__main__":
    unittest.main()
