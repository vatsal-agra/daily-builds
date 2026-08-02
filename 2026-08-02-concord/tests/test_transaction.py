import unittest

from concord import curve
from concord.transaction import Transaction, TxInput, TxOutput


def make_funded_output(address, amount=100):
    """A fake prior transaction whose single output we can spend in tests."""
    d = curve.generate_private_key()
    dummy_in = TxInput("f" * 64, 0, pubkey=curve.compress_pubkey(curve.private_to_public(d)))
    funding_tx = Transaction([dummy_in], [TxOutput(amount, address)])
    return funding_tx


class TestTransaction(unittest.TestCase):
    def setUp(self):
        self.d = curve.generate_private_key()
        self.q = curve.private_to_public(self.d)
        self.pubkey = curve.compress_pubkey(self.q)
        self.address = curve.pubkey_to_address(self.q)
        self.to_addr = curve.pubkey_to_address(curve.private_to_public(curve.generate_private_key()))

    def _spend_tx(self, funding_txid, amount, out_amount):
        inp = TxInput(funding_txid, 0, pubkey=self.pubkey)
        tx = Transaction([inp], [TxOutput(out_amount, self.to_addr)])
        tx.sign_input(0, self.d)
        return tx

    def test_sign_and_verify_roundtrip(self):
        funding = make_funded_output(self.address)
        tx = self._spend_tx(funding.txid(), 100, 90)
        self.assertTrue(tx.verify_input_signature(0))

    def test_tampered_output_amount_breaks_signature(self):
        funding = make_funded_output(self.address)
        tx = self._spend_tx(funding.txid(), 100, 90)
        tx.outputs[0].amount = 999999
        self.assertFalse(tx.verify_input_signature(0))

    def test_tampered_destination_breaks_signature(self):
        funding = make_funded_output(self.address)
        tx = self._spend_tx(funding.txid(), 100, 90)
        tx.outputs[0].address = "someone-else"
        self.assertFalse(tx.verify_input_signature(0))

    def test_splicing_signature_into_different_outputs_fails(self):
        funding = make_funded_output(self.address)
        tx = self._spend_tx(funding.txid(), 100, 90)
        sig = tx.inputs[0].signature
        forged = Transaction(
            [TxInput(funding.txid(), 0, pubkey=self.pubkey, signature=sig)],
            [TxOutput(90, "attacker-address-instead")],
        )
        self.assertFalse(forged.verify_input_signature(0))

    def test_missing_signature_fails_verify(self):
        inp = TxInput("a" * 64, 0, pubkey=self.pubkey)
        tx = Transaction([inp], [TxOutput(10, self.to_addr)])
        self.assertFalse(tx.verify_input_signature(0))

    def test_coinbase_recognition(self):
        cb = Transaction.new_coinbase(self.address, 50, height=1)
        self.assertTrue(cb.is_coinbase)
        funding = make_funded_output(self.address)
        normal = self._spend_tx(funding.txid(), 100, 90)
        self.assertFalse(normal.is_coinbase)

    def test_txid_deterministic_for_same_content(self):
        funding = make_funded_output(self.address)
        tx1 = self._spend_tx(funding.txid(), 100, 90)
        self.assertEqual(tx1.txid(), tx1.txid())

    def test_two_coinbases_same_reward_have_different_txids(self):
        cb1 = Transaction.new_coinbase(self.address, 50, height=5, extra="a")
        cb2 = Transaction.new_coinbase(self.address, 50, height=5, extra="b")
        self.assertNotEqual(cb1.txid(), cb2.txid())

    def test_negative_output_amount_rejected(self):
        with self.assertRaises(ValueError):
            TxOutput(-1, self.to_addr)

    def test_total_output_sums_all_outputs(self):
        tx = Transaction(
            [TxInput("a" * 64, 0, pubkey=self.pubkey)],
            [TxOutput(30, self.to_addr), TxOutput(20, self.address)],
        )
        self.assertEqual(tx.total_output(), 50)

    def test_to_dict_from_dict_roundtrip_preserves_txid(self):
        funding = make_funded_output(self.address)
        tx = self._spend_tx(funding.txid(), 100, 90)
        restored = Transaction.from_dict(tx.to_dict())
        self.assertEqual(tx.txid(), restored.txid())
        self.assertTrue(restored.verify_input_signature(0))


if __name__ == "__main__":
    unittest.main()
