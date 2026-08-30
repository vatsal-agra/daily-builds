import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import blockchain as bc
import crypto as c
import transaction as tx
from helpers import make_genesis, mine_on_top
from wallet import InsufficientFunds, Wallet


class TestWallet(unittest.TestCase):
    def setUp(self):
        self.genesis = make_genesis()
        self.chain = bc.Blockchain(self.genesis)
        self.alice = Wallet()
        self.bob = Wallet()
        cb = tx.Transaction.coinbase(self.alice.pubkey_hash, reward=bc.subsidy_at(1), height=1)
        b1 = mine_on_top(self.chain, self.chain.genesis_hash, [cb], 1_000_001)
        self.chain.accept_block(b1)
        self.cb = cb

    def test_balance_reflects_utxo_set(self):
        self.assertEqual(self.alice.balance(self.chain.utxo_set()), bc.subsidy_at(1))
        self.assertEqual(self.bob.balance(self.chain.utxo_set()), 0)

    def test_address_is_stable_and_valid_base58check(self):
        addr1 = self.alice.address
        addr2 = self.alice.address
        self.assertEqual(addr1, addr2)
        self.assertEqual(c.address_to_pubkey_hash(addr1), self.alice.pubkey_hash)

    def test_create_transaction_end_to_end(self):
        amount = 5_00000000
        t = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, amount, fee=1000)
        ok, reason = t.verify(lambda txid, idx: self.chain.utxo_set().get((txid, idx)))
        self.assertTrue(ok, reason)
        self.assertEqual(t.fee(lambda txid, idx: self.chain.utxo_set().get((txid, idx))), 1000)
        # exactly one output pays bob the requested amount
        bob_outs = [o for o in t.outputs if o.pubkey_hash == self.bob.pubkey_hash]
        self.assertEqual(len(bob_outs), 1)
        self.assertEqual(bob_outs[0].amount, amount)

    def test_insufficient_funds_raises(self):
        with self.assertRaises(InsufficientFunds):
            self.bob.create_transaction(self.chain.utxo_set(), self.alice.address, 1, fee=0)

    def test_change_output_present_when_overpaying_input(self):
        t = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, 1_00000000, fee=500)
        change_outs = [o for o in t.outputs if o.pubkey_hash == self.alice.pubkey_hash]
        self.assertEqual(len(change_outs), 1)
        expected_change = self.cb.total_output() - 1_00000000 - 500
        self.assertEqual(change_outs[0].amount, expected_change)

    def test_exact_amount_leaves_no_dust_change_output(self):
        exact = self.cb.total_output() - 500
        t = self.alice.create_transaction(self.chain.utxo_set(), self.bob.address, exact, fee=500)
        change_outs = [o for o in t.outputs if o.pubkey_hash == self.alice.pubkey_hash]
        self.assertEqual(len(change_outs), 0)


if __name__ == "__main__":
    unittest.main()
