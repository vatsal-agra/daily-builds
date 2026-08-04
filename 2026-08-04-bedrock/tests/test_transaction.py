import unittest

from bedrock import crypto
from bedrock.transaction import Transaction, TxInput, TxOutput


class TestTransactionSerialization(unittest.TestCase):
    def test_roundtrip_simple(self):
        tx = Transaction(version=1, inputs=[], outputs=[TxOutput(100, "addr1")], coinbase_data=b"genesis")
        raw = tx.to_bytes()
        restored, offset = Transaction.from_bytes(raw)
        self.assertEqual(offset, len(raw))
        self.assertEqual(restored.txid, tx.txid)
        self.assertEqual(restored.outputs[0].value, 100)
        self.assertEqual(restored.outputs[0].address, "addr1")

    def test_roundtrip_with_inputs(self):
        tx_in = TxInput(prev_txid="ab" * 32, prev_index=1, pubkey=b"\x02" + b"\x01" * 32, signature=b"\x03" * 64)
        tx = Transaction(version=1, inputs=[tx_in], outputs=[TxOutput(5, "addr2")])
        restored, _ = Transaction.from_bytes(tx.to_bytes())
        self.assertEqual(restored.inputs[0].prev_txid, tx_in.prev_txid)
        self.assertEqual(restored.inputs[0].prev_index, 1)
        self.assertEqual(restored.inputs[0].pubkey, tx_in.pubkey)
        self.assertEqual(restored.inputs[0].signature, tx_in.signature)

    def test_txid_changes_with_content(self):
        tx1 = Transaction(version=1, inputs=[], outputs=[TxOutput(1, "a")], coinbase_data=b"x")
        tx2 = Transaction(version=1, inputs=[], outputs=[TxOutput(2, "a")], coinbase_data=b"x")
        self.assertNotEqual(tx1.txid, tx2.txid)

    def test_negative_output_value_rejected(self):
        tx = Transaction(version=1, inputs=[], outputs=[TxOutput(-1, "a")])
        with self.assertRaises(Exception):
            tx.to_bytes()


class TestSigning(unittest.TestCase):
    def setUp(self):
        self.priv = crypto.generate_private_key()
        self.pub = crypto.derive_public_key(self.priv)
        self.addr = crypto.pubkey_to_address(self.pub)

    def test_single_input_sign_and_verify(self):
        tx = Transaction(
            version=1,
            inputs=[TxInput(prev_txid="00" * 32, prev_index=0)],
            outputs=[TxOutput(100, "recipient")],
        )
        tx.sign_input(0, self.priv, self.pub)
        self.assertTrue(tx.verify_input_signature(0))
        self.assertEqual(tx.input_owner_address(0), self.addr)

    def test_multi_input_sign_order_does_not_invalidate_earlier_signatures(self):
        # Regression for REVIEW.md #1: signing input 1 used to change the
        # sighash input 0 had already signed over, because the old sighash
        # design included every input's (possibly not-yet-set) pubkey bytes.
        priv2 = crypto.generate_private_key()
        pub2 = crypto.derive_public_key(priv2)
        tx = Transaction(
            version=1,
            inputs=[
                TxInput(prev_txid="11" * 32, prev_index=0),
                TxInput(prev_txid="22" * 32, prev_index=1),
            ],
            outputs=[TxOutput(50, "recipient")],
        )
        tx.sign_input(0, self.priv, self.pub)
        self.assertTrue(tx.verify_input_signature(0), "input 0 signature valid immediately after signing")
        tx.sign_input(1, priv2, pub2)
        self.assertTrue(tx.verify_input_signature(0), "input 0 signature must STILL be valid after input 1 is signed")
        self.assertTrue(tx.verify_input_signature(1))

    def test_signing_in_reverse_order_also_works(self):
        priv2 = crypto.generate_private_key()
        pub2 = crypto.derive_public_key(priv2)
        tx = Transaction(
            version=1,
            inputs=[
                TxInput(prev_txid="11" * 32, prev_index=0),
                TxInput(prev_txid="22" * 32, prev_index=1),
            ],
            outputs=[TxOutput(50, "recipient")],
        )
        tx.sign_input(1, priv2, pub2)
        tx.sign_input(0, self.priv, self.pub)
        self.assertTrue(tx.verify_input_signature(0))
        self.assertTrue(tx.verify_input_signature(1))

    def test_tampered_output_invalidates_signature(self):
        tx = Transaction(
            version=1,
            inputs=[TxInput(prev_txid="00" * 32, prev_index=0)],
            outputs=[TxOutput(100, "recipient")],
        )
        tx.sign_input(0, self.priv, self.pub)
        tx.outputs[0].value = 999999
        self.assertFalse(tx.verify_input_signature(0))

    def test_signature_does_not_transfer_to_different_transaction(self):
        tx_a = Transaction(version=1, inputs=[TxInput(prev_txid="33" * 32, prev_index=0)], outputs=[TxOutput(1, "x")])
        tx_a.sign_input(0, self.priv, self.pub)
        stolen_sig, stolen_pubkey = tx_a.inputs[0].signature, tx_a.inputs[0].pubkey

        tx_b = Transaction(version=1, inputs=[TxInput(prev_txid="33" * 32, prev_index=0)], outputs=[TxOutput(999, "attacker")])
        tx_b.inputs[0].signature = stolen_sig
        tx_b.inputs[0].pubkey = stolen_pubkey
        self.assertFalse(tx_b.verify_input_signature(0))

    def test_unsigned_input_fails_verification(self):
        tx = Transaction(version=1, inputs=[TxInput(prev_txid="00" * 32, prev_index=0)], outputs=[TxOutput(1, "x")])
        self.assertFalse(tx.verify_input_signature(0))


if __name__ == "__main__":
    unittest.main()
