import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import crypto as c
import transaction as tx


def make_utxo(owner_kp, amount=1000):
    prev_txid = c.hash256(os.urandom(8))
    out = tx.TxOut(amount=amount, pubkey_hash=c.hash160(owner_kp.pubkey_bytes()))
    utxos = {(prev_txid, 0): out}
    return prev_txid, out, (lambda txid, idx: utxos.get((txid, idx)))


class TestTransactionValidity(unittest.TestCase):
    def setUp(self):
        self.alice = c.KeyPair.generate()
        self.bob = c.KeyPair.generate()
        self.prev_txid, self.prevout, self.lookup = make_utxo(self.alice, amount=1000)

    def _spend(self, amount_out, signer_privkey=None, spender_pubkey=None):
        t = tx.Transaction(
            inputs=[tx.TxIn(prev_txid=self.prev_txid, prev_index=0,
                             pubkey=spender_pubkey or self.alice.pubkey_bytes())],
            outputs=[tx.TxOut(amount=amount_out, pubkey_hash=c.hash160(self.bob.pubkey_bytes()))],
        )
        t.sign_input(0, signer_privkey if signer_privkey is not None else self.alice.private_key)
        return t

    def test_valid_spend_verifies(self):
        t = self._spend(900)
        ok, reason = t.verify(self.lookup)
        self.assertTrue(ok, reason)

    def test_serialize_roundtrip_preserves_txid(self):
        t = self._spend(900)
        raw = t.serialize()
        t2, off = tx.Transaction.deserialize(raw)
        self.assertEqual(off, len(raw))
        self.assertEqual(t2.txid(), t.txid())

    def test_tampered_output_amount_after_signing_fails(self):
        t = self._spend(900)
        t.outputs[0].amount = 999999
        ok, _ = t.verify(self.lookup)
        self.assertFalse(ok)

    def test_wrong_private_key_fails(self):
        t = self._spend(900, signer_privkey=self.bob.private_key)  # claims alice's pubkey, signs with bob's key
        ok, reason = t.verify(self.lookup)
        self.assertFalse(ok)
        self.assertIn("signature", reason)

    def test_pubkey_not_matching_output_lock_fails(self):
        t = self._spend(900, spender_pubkey=self.bob.pubkey_bytes())
        ok, reason = t.verify(self.lookup)
        self.assertFalse(ok)
        self.assertIn("does not match", reason)

    def test_missing_prevout_fails(self):
        t = tx.Transaction(
            inputs=[tx.TxIn(prev_txid=c.hash256(b"nope"), prev_index=0, pubkey=self.alice.pubkey_bytes())],
            outputs=[tx.TxOut(amount=1, pubkey_hash=c.hash160(self.bob.pubkey_bytes()))],
        )
        t.sign_input(0, self.alice.private_key)
        ok, reason = t.verify(self.lookup)
        self.assertFalse(ok)
        self.assertIn("missing", reason)

    def test_spending_more_than_input_value_fails(self):
        t = self._spend(1_000_000)
        ok, reason = t.verify(self.lookup)
        self.assertFalse(ok)
        self.assertIn("cover", reason)

    def test_unsigned_input_fails(self):
        t = tx.Transaction(
            inputs=[tx.TxIn(prev_txid=self.prev_txid, prev_index=0, pubkey=self.alice.pubkey_bytes())],
            outputs=[tx.TxOut(amount=900, pubkey_hash=c.hash160(self.bob.pubkey_bytes()))],
        )
        ok, reason = t.verify(self.lookup)
        self.assertFalse(ok)
        self.assertIn("unsigned", reason)

    def test_duplicate_input_within_one_tx_fails(self):
        t = tx.Transaction(
            inputs=[
                tx.TxIn(prev_txid=self.prev_txid, prev_index=0, pubkey=self.alice.pubkey_bytes()),
                tx.TxIn(prev_txid=self.prev_txid, prev_index=0, pubkey=self.alice.pubkey_bytes()),
            ],
            outputs=[tx.TxOut(amount=1, pubkey_hash=c.hash160(self.bob.pubkey_bytes()))],
        )
        t.sign_input(0, self.alice.private_key)
        t.sign_input(1, self.alice.private_key)
        ok, reason = t.verify(self.lookup)
        self.assertFalse(ok)
        self.assertIn("two inputs", reason)

    def test_no_inputs_or_no_outputs_rejected(self):
        empty_in = tx.Transaction(inputs=[], outputs=[tx.TxOut(1, b"\x00" * 20)])
        ok, _ = empty_in.verify(self.lookup)
        self.assertFalse(ok)
        empty_out = tx.Transaction(inputs=[tx.TxIn(self.prev_txid, 0, self.alice.pubkey_bytes())], outputs=[])
        ok, _ = empty_out.verify(self.lookup)
        self.assertFalse(ok)

    def test_fee_computation(self):
        t = self._spend(900)
        self.assertEqual(t.fee(self.lookup), 100)

    def test_coinbase_verifies_and_reports_zero_fee(self):
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=5000, height=3)
        ok, reason = cb.verify(self.lookup)
        self.assertTrue(ok, reason)
        self.assertEqual(cb.fee(self.lookup), 0)

    def test_coinbase_with_extra_inputs_rejected(self):
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=5000, height=3)
        cb.inputs.append(tx.TxIn(prev_txid=self.prev_txid, prev_index=0, pubkey=self.alice.pubkey_bytes()))
        ok, reason = cb.verify(self.lookup)
        self.assertFalse(ok)
        self.assertIn("sole input", reason)


if __name__ == "__main__":
    unittest.main()
