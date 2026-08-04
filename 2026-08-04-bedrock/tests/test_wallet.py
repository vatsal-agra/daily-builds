import unittest

from bedrock.chain import COIN
from bedrock.node import Node
from bedrock.wallet import Wallet, WalletError


class TestWallet(unittest.TestCase):
    def setUp(self):
        self.node = Node()
        self.alice = Wallet.generate()
        self.bob = Wallet.generate()

    def test_balance_zero_before_any_reward(self):
        self.assertEqual(self.alice.balance(self.node.chain), 0)

    def test_balance_after_mining(self):
        self.node.mine_block(self.alice.address)
        self.assertEqual(self.alice.balance(self.node.chain), 5_000_000_000)

    def test_send_updates_balances_after_mining(self):
        self.node.mine_block(self.alice.address)
        self.alice.send(self.node.chain, self.node.mempool, self.bob.address, 10 * COIN, fee=100)
        self.node.mine_block(self.alice.address)
        self.assertEqual(self.bob.balance(self.node.chain), 10 * COIN)

    def test_insufficient_funds_raises_clean_error(self):
        with self.assertRaises(WalletError):
            self.alice.build_transaction(self.node.chain, self.bob.address, 1, fee=0)

    def test_zero_amount_rejected(self):
        self.node.mine_block(self.alice.address)
        with self.assertRaises(WalletError):
            self.alice.build_transaction(self.node.chain, self.bob.address, 0, fee=0)

    def test_negative_amount_rejected(self):
        self.node.mine_block(self.alice.address)
        with self.assertRaises(WalletError):
            self.alice.build_transaction(self.node.chain, self.bob.address, -100, fee=0)

    def test_negative_fee_rejected(self):
        self.node.mine_block(self.alice.address)
        with self.assertRaises(WalletError):
            self.alice.build_transaction(self.node.chain, self.bob.address, 100, fee=-1)

    def test_invalid_recipient_address_rejected(self):
        self.node.mine_block(self.alice.address)
        with self.assertRaises(WalletError):
            self.alice.build_transaction(self.node.chain, "not-a-real-address", 100, fee=0)

    def test_multi_utxo_transaction_is_fully_valid(self):
        # Regression: give alice two separate UTXOs so building a transaction
        # requires combining both as inputs, and confirm every input's
        # signature independently verifies (see REVIEW.md #1).
        self.node.mine_block(self.alice.address)
        self.node.mine_block(self.alice.address)
        total = self.alice.balance(self.node.chain)
        tx = self.alice.build_transaction(self.node.chain, self.bob.address, total - 1000, fee=1000)
        self.assertGreaterEqual(len(tx.inputs), 2)
        for i in range(len(tx.inputs)):
            self.assertTrue(tx.verify_input_signature(i), f"input {i} signature invalid")

    def test_change_output_returned_to_sender(self):
        self.node.mine_block(self.alice.address)
        balance = self.alice.balance(self.node.chain)
        tx = self.alice.build_transaction(self.node.chain, self.bob.address, 1 * COIN, fee=100)
        change_outputs = [o for o in tx.outputs if o.address == self.alice.address]
        self.assertEqual(len(change_outputs), 1)
        self.assertEqual(change_outputs[0].value, balance - 1 * COIN - 100)

    def test_no_change_output_when_exact_amount(self):
        self.node.mine_block(self.alice.address)
        balance = self.alice.balance(self.node.chain)
        tx = self.alice.build_transaction(self.node.chain, self.bob.address, balance - 100, fee=100)
        self.assertEqual(len(tx.outputs), 1)

    def test_wallet_from_wif_roundtrip(self):
        wif = self.alice.to_wif()
        restored = Wallet.from_wif(wif)
        self.assertEqual(restored.address, self.alice.address)


if __name__ == "__main__":
    unittest.main()
