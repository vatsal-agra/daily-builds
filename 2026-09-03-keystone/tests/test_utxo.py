import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone.block import Block, BlockHeader
from keystone.transaction import Transaction, TxIn, TxOut, make_coinbase
from keystone.utxo import UTXOSet, ValidationError, COINBASE_MATURITY
from keystone.wallet import Wallet


def make_block(transactions, height=1, prev_hash="0" * 64):
    header = BlockHeader(version=1, prev_hash=prev_hash, merkle_root="", timestamp=height, bits=0, nonce=0)
    blk = Block(header=header, transactions=transactions, height=height)
    blk.header.merkle_root = blk.compute_merkle_root()
    return blk


class TestCoinbaseValidation(unittest.TestCase):
    def setUp(self):
        self.utxo = UTXOSet()
        self.miner = Wallet.generate()

    def test_valid_coinbase_applies(self):
        cb = make_coinbase(self.miner.lock_script_for_self(), 5000, height=0, extra_nonce=0)
        blk = make_block([cb], height=0)
        removed = self.utxo.validate_and_apply_block(blk, block_reward=5000)
        self.assertEqual(removed, [])
        self.assertEqual(self.utxo.balance_of(self.miner.pubkey_hash), 5000)

    def test_coinbase_overpay_rejected(self):
        cb = make_coinbase(self.miner.lock_script_for_self(), 6000, height=0, extra_nonce=0)
        blk = make_block([cb], height=0)
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_negative_coinbase_output_rejected(self):
        """Regression test for REVIEW.md finding #3."""
        cb = make_coinbase(self.miner.lock_script_for_self(), -1000, height=0, extra_nonce=0)
        blk = make_block([cb], height=0)
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)
        # and state must be completely unchanged after a rejected block
        self.assertEqual(self.utxo.balance_of(self.miner.pubkey_hash), 0)

    def test_missing_coinbase_rejected(self):
        blk = make_block([], height=0)
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_second_coinbase_rejected(self):
        cb1 = make_coinbase(self.miner.lock_script_for_self(), 5000, height=0, extra_nonce=0)
        cb2 = make_coinbase(self.miner.lock_script_for_self(), 5000, height=0, extra_nonce=1)
        blk = make_block([cb1, cb2], height=0)
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_duplicate_txid_in_block_rejected(self):
        cb = make_coinbase(self.miner.lock_script_for_self(), 5000, height=0, extra_nonce=0)
        # deliberately reuse the exact same coinbase tx object twice
        blk = make_block([cb, cb], height=0)
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)


class TestSpendValidation(unittest.TestCase):
    def setUp(self):
        self.utxo = UTXOSet()
        self.alice = Wallet.generate()
        self.bob = Wallet.generate()
        cb = make_coinbase(self.alice.lock_script_for_self(), 5000, height=0, extra_nonce=0)
        blk = make_block([cb], height=0)
        self.utxo.validate_and_apply_block(blk, block_reward=5000)
        self.utxo_txid = cb.txid()

    def _spend_tx(self, amount_out, to=None):
        to = to or self.bob
        return self.alice.build_transaction([(self.utxo_txid, 0)], [(amount_out, to.pubkey_hash)])

    def test_valid_spend_after_maturity(self):
        tx = self._spend_tx(4000)
        blk = make_block([make_coinbase(self.alice.lock_script_for_self(), 5000, COINBASE_MATURITY, 0), tx],
                          height=COINBASE_MATURITY)
        removed = self.utxo.validate_and_apply_block(blk, block_reward=5000)
        self.assertEqual(len(removed), 1)
        self.assertEqual(self.utxo.balance_of(self.bob.pubkey_hash), 4000)

    def test_immature_coinbase_spend_rejected(self):
        tx = self._spend_tx(4000)
        blk = make_block([make_coinbase(self.alice.lock_script_for_self(), 5000, 1, 0), tx], height=1)
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_double_spend_within_block_rejected(self):
        tx1 = self._spend_tx(2000, self.bob)
        tx2 = self.alice.build_transaction([(self.utxo_txid, 0)], [(2000, self.bob.pubkey_hash)])
        blk = make_block(
            [make_coinbase(self.alice.lock_script_for_self(), 5000, COINBASE_MATURITY, 0), tx1, tx2],
            height=COINBASE_MATURITY,
        )
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_spend_nonexistent_output_rejected(self):
        forged = self.alice.build_transaction([("f" * 64, 0)], [(100, self.bob.pubkey_hash)])
        blk = make_block(
            [make_coinbase(self.alice.lock_script_for_self(), 5000, COINBASE_MATURITY, 0), forged],
            height=COINBASE_MATURITY,
        )
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_outputs_exceeding_inputs_rejected(self):
        tx = self._spend_tx(999999)
        blk = make_block(
            [make_coinbase(self.alice.lock_script_for_self(), 5000, COINBASE_MATURITY, 0), tx],
            height=COINBASE_MATURITY,
        )
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_wrong_signer_rejected(self):
        forged = self.bob.build_transaction([(self.utxo_txid, 0)], [(4000, self.bob.pubkey_hash)])
        blk = make_block(
            [make_coinbase(self.alice.lock_script_for_self(), 5000, COINBASE_MATURITY, 0), forged],
            height=COINBASE_MATURITY,
        )
        with self.assertRaises(ValidationError):
            self.utxo.validate_and_apply_block(blk, block_reward=5000)

    def test_empty_input_non_coinbase_tx_rejected(self):
        """Regression test for REVIEW.md finding #4."""
        empty_tx = Transaction(inputs=[], outputs=[])
        with self.assertRaises(ValidationError):
            self.utxo._validate_transaction(empty_tx, set(), current_height=0)

    def test_undo_block_restores_exact_prior_state(self):
        tx = self._spend_tx(4000)
        blk = make_block(
            [make_coinbase(self.alice.lock_script_for_self(), 5000, COINBASE_MATURITY, 0), tx],
            height=COINBASE_MATURITY,
        )
        snapshot_before = self.utxo.snapshot()
        removed = self.utxo.validate_and_apply_block(blk, block_reward=5000)
        self.assertNotEqual(self.utxo.snapshot(), snapshot_before)
        self.utxo.undo_block(blk, removed)
        self.assertEqual(self.utxo.snapshot(), snapshot_before)


if __name__ == "__main__":
    unittest.main()
