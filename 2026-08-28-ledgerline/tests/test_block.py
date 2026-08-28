import time
import unittest

from ledgerline.block import (
    Block, BlockHeader, GENESIS_PREV_HASH, difficulty_from_bits, make_genesis_block,
    mine_block, target_from_bits, validate_block_shape,
)
from ledgerline.transaction import Transaction, TxOut, build_transaction, make_coinbase
from ledgerline.wallet import Wallet

BITS = 10  # cheap enough for a fast test suite


class TestTargetMath(unittest.TestCase):
    def test_higher_bits_means_smaller_target(self):
        self.assertGreater(target_from_bits(1), target_from_bits(10))

    def test_difficulty_doubles_per_bit(self):
        self.assertEqual(difficulty_from_bits(5) * 2, difficulty_from_bits(6))


class TestMining(unittest.TestCase):
    def test_mine_block_finds_valid_nonce(self):
        alice = Wallet()
        cb = make_coinbase(alice.address, 50, height=0)
        genesis = make_genesis_block(cb, bits=BITS)
        self.assertTrue(genesis.header.meets_target())
        self.assertIsNone(validate_block_shape(genesis))

    def test_stop_flag_aborts_mining(self):
        alice = Wallet()
        cb = make_coinbase(alice.address, 50, height=1)
        header = BlockHeader(1, GENESIS_PREV_HASH, "", time.time(), bits=63, nonce=0, height=1)
        block = Block(header, [cb])
        header.merkle_root_hex = block.compute_merkle_root()
        found = mine_block(block, stop_flag=lambda: True)  # aborts immediately
        self.assertFalse(found)

    def test_mine_block_exhausts_nonce_space_gracefully(self):
        alice = Wallet()
        cb = make_coinbase(alice.address, 50, height=1)
        header = BlockHeader(1, GENESIS_PREV_HASH, "", time.time(), bits=63, nonce=0, height=1)
        block = Block(header, [cb])
        header.merkle_root_hex = block.compute_merkle_root()
        found = mine_block(block, stop_flag=lambda: False, max_nonce=50)
        self.assertFalse(found)


class TestBlockShapeValidation(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()
        cb = make_coinbase(self.alice.address, 50, height=0)
        self.genesis = make_genesis_block(cb, bits=BITS)

    def _mined_block(self, txs, height=1, bits=BITS):
        header = BlockHeader(1, self.genesis.hash_hex(), "", time.time(), bits, 0, height)
        block = Block(header, txs)
        header.merkle_root_hex = block.compute_merkle_root()
        mine_block(block, stop_flag=lambda: False)
        return block

    def test_valid_block_passes(self):
        cb = make_coinbase(self.bob.address, 50, height=1)
        block = self._mined_block([cb])
        self.assertIsNone(validate_block_shape(block))

    def test_no_transactions_rejected(self):
        header = BlockHeader(1, self.genesis.hash_hex(), "a" * 64, time.time(), BITS, 0, 1)
        block = Block(header, [])
        self.assertIsNotNone(validate_block_shape(block))

    def test_missing_coinbase_rejected(self):
        utxos = [(self.genesis.transactions[0].txid(), 0, 50)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 10, 1, self.alice.address)
        block = self._mined_block([tx])
        err = validate_block_shape(block)
        self.assertIsNotNone(err)
        self.assertIn("coinbase", err)

    def test_second_coinbase_rejected(self):
        cb1 = make_coinbase(self.bob.address, 50, height=1)
        cb2 = make_coinbase(self.alice.address, 50, height=1, extra_nonce=1)
        block = self._mined_block([cb1, cb2])
        err = validate_block_shape(block)
        self.assertIsNotNone(err)

    def test_bad_merkle_root_rejected(self):
        cb = make_coinbase(self.bob.address, 50, height=1)
        block = self._mined_block([cb])
        block.header.merkle_root_hex = "0" * 64
        # re-mine so PoW still passes but merkle root is now wrong
        mine_block(block, stop_flag=lambda: False)
        err = validate_block_shape(block)
        self.assertIsNotNone(err)
        self.assertIn("merkle", err)

    def test_unmet_pow_target_rejected(self):
        cb = make_coinbase(self.bob.address, 50, height=1)
        header = BlockHeader(1, self.genesis.hash_hex(), "", time.time(), 63, 0, 1)
        block = Block(header, [cb])
        header.merkle_root_hex = block.compute_merkle_root()
        # deliberately don't mine: nonce=0 essentially never satisfies bits=63
        err = validate_block_shape(block)
        self.assertIsNotNone(err)
        self.assertIn("proof-of-work", err)

    def test_invalid_signature_in_block_rejected(self):
        utxos = [(self.genesis.transactions[0].txid(), 0, 50)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 10, 1, self.alice.address)
        tx.outputs[0].amount = 999999  # tamper after signing
        cb = make_coinbase(self.bob.address, 51, height=1)
        block = self._mined_block([cb, tx])
        err = validate_block_shape(block)
        self.assertIsNotNone(err)

    def test_duplicate_txids_rejected(self):
        utxos = [(self.genesis.transactions[0].txid(), 0, 50)]
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 10, 1, self.alice.address)
        cb = make_coinbase(self.bob.address, 51, height=1)
        # the exact same non-coinbase tx appearing twice must be rejected
        # (this exercises the duplicate-txid check specifically, distinct
        # from the "only one coinbase" check above)
        header = BlockHeader(1, self.genesis.hash_hex(), "", time.time(), BITS, 0, 1)
        block = Block(header, [cb, tx, tx])
        header.merkle_root_hex = block.compute_merkle_root()
        mine_block(block, stop_flag=lambda: False)
        err = validate_block_shape(block)
        self.assertIsNotNone(err)
        self.assertIn("duplicate", err)


if __name__ == "__main__":
    unittest.main()
