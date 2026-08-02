import unittest

from concord import pow as powmod
from concord.block import Block
from concord.chain import BASE_REWARD, Blockchain
from concord.mempool import Mempool, MempoolRejected
from concord.transaction import Transaction, TxInput, TxOutput
from concord.wallet import Wallet

EASY_TARGET = powmod.MAX_TARGET >> 8


def mine(block):
    while not powmod.meets_target(bytes.fromhex(block.hash()), block.target):
        block.nonce += 1
    return block


def fresh_chain(amount=1000):
    alice = Wallet()
    genesis = Block.genesis(alice.address, EASY_TARGET, amount=amount)
    return Blockchain(genesis), alice


class TestMempool(unittest.TestCase):
    def setUp(self):
        self.chain, self.alice = fresh_chain()
        self.bob = Wallet()
        self.mempool = Mempool()

    def test_accepts_valid_transaction(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        fee = self.mempool.add_transaction(tx, self.chain.utxo)
        self.assertEqual(fee, 0)
        self.assertIn(tx.txid(), self.mempool)

    def test_computes_fee_correctly(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100, fee=7)
        fee = self.mempool.add_transaction(tx, self.chain.utxo)
        self.assertEqual(fee, 7)

    def test_rejects_coinbase(self):
        cb = Transaction.new_coinbase(self.alice.address, BASE_REWARD, height=1)
        with self.assertRaises(MempoolRejected):
            self.mempool.add_transaction(cb, self.chain.utxo)

    def test_rejects_spend_of_unknown_output(self):
        bogus = TxInput("ff" * 32, 0, pubkey=self.alice.pubkey_bytes)
        tx = Transaction([bogus], [TxOutput(1, self.bob.address)])
        tx.sign_input(0, self.alice.private_key)
        with self.assertRaises(MempoolRejected):
            self.mempool.add_transaction(tx, self.chain.utxo)

    def test_rejects_invalid_signature(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        tx.inputs[0].signature = bytes(b ^ 1 for b in tx.inputs[0].signature)
        with self.assertRaises(MempoolRejected):
            self.mempool.add_transaction(tx, self.chain.utxo)

    def test_rejects_outputs_exceeding_inputs(self):
        key = next(iter(self.chain.utxo))
        amount = self.chain.utxo[key].amount
        inp = TxInput(key[0], key[1], pubkey=self.alice.pubkey_bytes)
        tx = Transaction([inp], [TxOutput(amount + 1, self.bob.address)])
        tx.sign_input(0, self.alice.private_key)
        with self.assertRaises(MempoolRejected):
            self.mempool.add_transaction(tx, self.chain.utxo)

    def test_double_insert_is_idempotent_not_conflict(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        self.mempool.add_transaction(tx, self.chain.utxo)
        # re-adding the exact same tx must not raise "already spent" against itself
        fee = self.mempool.add_transaction(tx, self.chain.utxo)
        self.assertEqual(fee, 0)
        self.assertEqual(len(self.mempool), 1)

    def test_rejects_double_spend_against_pending_transaction(self):
        tx1 = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        self.mempool.add_transaction(tx1, self.chain.utxo)
        carol = Wallet()
        conflict = Transaction(
            [TxInput(tx1.inputs[0].txid, tx1.inputs[0].index, pubkey=self.alice.pubkey_bytes)],
            [TxOutput(50, carol.address)],
        )
        conflict.sign_input(0, self.alice.private_key)
        with self.assertRaises(MempoolRejected):
            self.mempool.add_transaction(conflict, self.chain.utxo)

    def test_remove_confirmed_frees_the_outpoint(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        self.mempool.add_transaction(tx, self.chain.utxo)
        self.mempool.remove_confirmed([tx.txid()])
        self.assertNotIn(tx.txid(), self.mempool)
        self.assertNotIn((tx.inputs[0].txid, tx.inputs[0].index), self.mempool._spent_outpoints)

    def test_prune_conflicts_drops_tx_whose_input_vanished(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        self.mempool.add_transaction(tx, self.chain.utxo)
        utxo_after_rivals_win = dict(self.chain.utxo)
        del utxo_after_rivals_win[(tx.inputs[0].txid, tx.inputs[0].index)]
        dropped = self.mempool.prune_conflicts(utxo_after_rivals_win)
        self.assertEqual(dropped, [tx.txid()])
        self.assertNotIn(tx.txid(), self.mempool)

    def test_prune_conflicts_keeps_still_valid_tx(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        self.mempool.add_transaction(tx, self.chain.utxo)
        dropped = self.mempool.prune_conflicts(self.chain.utxo)
        self.assertEqual(dropped, [])
        self.assertIn(tx.txid(), self.mempool)

    def test_reintroduce_drops_now_invalid_and_keeps_valid(self):
        tx_valid = self.alice.build_transaction(self.chain.utxo, self.bob.address, 50)
        restored = self.mempool.reintroduce([tx_valid], self.chain.utxo)
        self.assertEqual(restored, [tx_valid.txid()])
        # a genuinely conflicting/invalid tx (spends what tx_valid already spent) is dropped, not raised
        conflict = self.alice.build_transaction(self.chain.utxo, self.bob.address, 50)
        restored2 = self.mempool.reintroduce([conflict], self.chain.utxo)
        self.assertEqual(restored2, [])


if __name__ == "__main__":
    unittest.main()
