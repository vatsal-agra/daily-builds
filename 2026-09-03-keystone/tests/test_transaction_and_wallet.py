import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone.transaction import Transaction, TxIn, TxOut, make_coinbase
from keystone.wallet import Wallet


class TestTransaction(unittest.TestCase):
    def test_txid_stable_for_same_content(self):
        tx1 = Transaction(inputs=[TxIn("a" * 64, 0, ["sig", "pub"])], outputs=[TxOut(100, ["OP_DUP"])])
        tx2 = Transaction(inputs=[TxIn("a" * 64, 0, ["sig", "pub"])], outputs=[TxOut(100, ["OP_DUP"])])
        self.assertEqual(tx1.txid(), tx2.txid())

    def test_txid_changes_with_content(self):
        tx1 = Transaction(inputs=[TxIn("a" * 64, 0)], outputs=[TxOut(100, [])])
        tx2 = Transaction(inputs=[TxIn("a" * 64, 0)], outputs=[TxOut(101, [])])
        self.assertNotEqual(tx1.txid(), tx2.txid())

    def test_signing_hash_excludes_script_sig(self):
        tx1 = Transaction(inputs=[TxIn("a" * 64, 0, script_sig=["sig1"])], outputs=[TxOut(100, [])])
        tx2 = Transaction(inputs=[TxIn("a" * 64, 0, script_sig=["sig2"])], outputs=[TxOut(100, [])])
        self.assertEqual(tx1.signing_hash(), tx2.signing_hash())
        self.assertNotEqual(tx1.txid(), tx2.txid())  # but txid still differs

    def test_signing_hash_includes_outputs(self):
        tx1 = Transaction(inputs=[TxIn("a" * 64, 0)], outputs=[TxOut(100, [])])
        tx2 = Transaction(inputs=[TxIn("a" * 64, 0)], outputs=[TxOut(200, [])])
        self.assertNotEqual(tx1.signing_hash(), tx2.signing_hash())

    def test_to_dict_from_dict_roundtrip(self):
        tx = Transaction(inputs=[TxIn("b" * 64, 1, ["s", "p"])], outputs=[TxOut(50, ["OP_DUP"])], locktime=7)
        rebuilt = Transaction.from_dict(tx.to_dict())
        self.assertEqual(tx.txid(), rebuilt.txid())
        self.assertEqual(tx.locktime, rebuilt.locktime)

    def test_coinbase_detection(self):
        cb = make_coinbase(["OP_DUP"], 5000, height=1, extra_nonce=0)
        self.assertTrue(cb.is_coinbase)
        normal = Transaction(inputs=[TxIn("c" * 64, 0)], outputs=[TxOut(1, [])])
        self.assertFalse(normal.is_coinbase)

    def test_coinbase_txids_unique_across_height_and_nonce(self):
        cb1 = make_coinbase(["script"], 5000, height=5, extra_nonce=0)
        cb2 = make_coinbase(["script"], 5000, height=6, extra_nonce=0)
        cb3 = make_coinbase(["script"], 5000, height=5, extra_nonce=1)
        ids = {cb1.txid(), cb2.txid(), cb3.txid()}
        self.assertEqual(len(ids), 3)

    def test_total_output(self):
        tx = Transaction(inputs=[], outputs=[TxOut(30, []), TxOut(70, [])])
        self.assertEqual(tx.total_output(), 100)


class TestWallet(unittest.TestCase):
    def test_address_derivation_deterministic(self):
        w1 = Wallet.from_privkey(12345)
        w2 = Wallet.from_privkey(12345)
        self.assertEqual(w1.address, w2.address)

    def test_different_keys_different_addresses(self):
        w1 = Wallet.generate()
        w2 = Wallet.generate()
        self.assertNotEqual(w1.address, w2.address)

    def test_address_roundtrip(self):
        w = Wallet.generate()
        pkh = Wallet.address_to_pubkey_hash(w.address)
        self.assertEqual(pkh, w.pubkey_hash)

    def test_build_transaction_signs_correctly(self):
        w = Wallet.generate()
        recipient = Wallet.generate()
        tx = w.build_transaction([("d" * 64, 0)], [(1000, recipient.pubkey_hash)])
        sighash = tx.signing_hash()
        from keystone import script
        self.assertTrue(script.execute(tx.inputs[0].script_sig, w.lock_script_for_self(), sighash))

    def test_bad_address_checksum_rejected(self):
        w = Wallet.generate()
        tampered = w.address[:-1] + ("1" if w.address[-1] != "1" else "2")
        with self.assertRaises(ValueError):
            Wallet.address_to_pubkey_hash(tampered)


if __name__ == "__main__":
    unittest.main()
