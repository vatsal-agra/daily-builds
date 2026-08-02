import unittest

from concord import pow as powmod
from concord.block import Block
from concord.chain import Blockchain
from concord.wallet import InsufficientFunds, Wallet

EASY_TARGET = powmod.MAX_TARGET >> 8


def fresh_chain(amount=1000):
    alice = Wallet()
    genesis = Block.genesis(alice.address, EASY_TARGET, amount=amount)
    return Blockchain(genesis), alice


class TestWallet(unittest.TestCase):
    def test_balance_reflects_utxo_set(self):
        chain, alice = fresh_chain(amount=555)
        self.assertEqual(alice.balance(chain.utxo), 555)

    def test_build_transaction_produces_signed_valid_tx(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        tx = alice.build_transaction(chain.utxo, bob.address, 200)
        self.assertTrue(tx.verify_input_signature(0))
        self.assertEqual(tx.total_output(), 1000)  # 200 to bob + 800 change, no fee

    def test_build_transaction_with_fee_deducts_correctly(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        tx = alice.build_transaction(chain.utxo, bob.address, 200, fee=10)
        self.assertEqual(tx.total_output(), 990)

    def test_exact_amount_produces_no_change_output(self):
        chain, alice = fresh_chain(amount=100)
        bob = Wallet()
        tx = alice.build_transaction(chain.utxo, bob.address, 100)
        self.assertEqual(len(tx.outputs), 1)

    def test_insufficient_funds_raises(self):
        chain, alice = fresh_chain(amount=50)
        bob = Wallet()
        with self.assertRaises(InsufficientFunds):
            alice.build_transaction(chain.utxo, bob.address, 51)

    def test_zero_or_negative_amount_rejected(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        with self.assertRaises(ValueError):
            alice.build_transaction(chain.utxo, bob.address, 0)
        with self.assertRaises(ValueError):
            alice.build_transaction(chain.utxo, bob.address, -5)

    def test_negative_fee_rejected(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        with self.assertRaises(ValueError):
            alice.build_transaction(chain.utxo, bob.address, 10, fee=-1)

    def test_invalid_destination_address_rejected(self):
        chain, alice = fresh_chain()
        with self.assertRaises(ValueError):
            alice.build_transaction(chain.utxo, "not-a-real-address", 10)

    def test_save_load_roundtrip(self, ):
        import tempfile, os
        alice = Wallet()
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            alice.save(path)
            loaded = Wallet.load(path)
            self.assertEqual(loaded.address, alice.address)
            self.assertEqual(loaded.private_key, alice.private_key)
        finally:
            os.remove(path)

    def test_load_or_create_creates_when_missing(self):
        import tempfile, os
        path = os.path.join(tempfile.mkdtemp(), "new_wallet.json")
        self.assertFalse(os.path.exists(path))
        w1 = Wallet.load_or_create(path)
        self.assertTrue(os.path.exists(path))
        w2 = Wallet.load_or_create(path)
        self.assertEqual(w1.address, w2.address)


if __name__ == "__main__":
    unittest.main()
