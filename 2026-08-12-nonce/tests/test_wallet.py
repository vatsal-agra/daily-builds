import unittest

from nonce.wallet import Wallet, InsufficientFunds
from nonce.core.blockchain import Blockchain, create_genesis
from nonce.crypto import secp256k1 as ec


class TestWallet(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()
        self.chain = Blockchain(create_genesis(self.alice.address))

    def test_new_wallet_has_valid_address(self):
        w = Wallet()
        self.assertTrue(w.address)
        self.assertEqual(w.pubkey, ec.privkey_to_pubkey(w.privkey))

    def test_zero_amount_rejected(self):
        with self.assertRaises(ValueError):
            self.alice.build_transaction(self.chain, self.bob.address, 0)

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            self.alice.build_transaction(self.chain, self.bob.address, -100)

    def test_invalid_recipient_address_rejected(self):
        with self.assertRaises(ValueError):
            self.alice.build_transaction(self.chain, "notAnAddress", 1000)

    def test_insufficient_funds_raises_specific_exception(self):
        with self.assertRaises(InsufficientFunds):
            self.alice.build_transaction(self.chain, self.bob.address, 10**18)

    def test_change_output_correct(self):
        balance_before = self.chain.balance(self.alice.address)
        tx = self.alice.build_transaction(self.chain, self.bob.address, 10_00000000, fee=1000)
        total_out = sum(o.amount for o in tx.outputs)
        total_in = sum(self.chain.utxo_set[(i.prev_txid, i.prev_index)].amount for i in tx.inputs)
        self.assertEqual(total_in - total_out, 1000)  # exactly the fee, no value created or lost
        self.assertLessEqual(total_in, balance_before)

    def test_recipient_output_present_and_correct(self):
        tx = self.alice.build_transaction(self.chain, self.bob.address, 7_00000000, fee=500)
        recipient_outputs = [o for o in tx.outputs if o.to_address == self.bob.address]
        self.assertEqual(len(recipient_outputs), 1)
        self.assertEqual(recipient_outputs[0].amount, 7_00000000)


if __name__ == "__main__":
    unittest.main()
