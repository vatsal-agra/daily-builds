import unittest

from bedrock.block import Block, BlockHeader, GENESIS_PREV_HASH
from bedrock.transaction import Transaction, TxOutput


def make_block():
    coinbase = Transaction(version=1, inputs=[], outputs=[TxOutput(50, "miner")], coinbase_data=b"test")
    header = BlockHeader(version=1, prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64, timestamp=1000, target=1 << 250, nonce=0)
    block = Block(header, [coinbase])
    header.merkle_root = block.compute_merkle_root()
    return block


class TestBlockSerialization(unittest.TestCase):
    def test_header_roundtrip(self):
        header = BlockHeader(version=1, prev_hash="ab" * 32, merkle_root="cd" * 32, timestamp=12345, target=1 << 200, nonce=999)
        restored, offset = BlockHeader.from_bytes(header.to_bytes())
        self.assertEqual(offset, len(header.to_bytes()))
        self.assertEqual(restored.hash, header.hash)
        self.assertEqual(restored.target, header.target)
        self.assertEqual(restored.nonce, 999)

    def test_block_roundtrip(self):
        block = make_block()
        restored, offset = Block.from_bytes(block.to_bytes())
        self.assertEqual(offset, len(block.to_bytes()))
        self.assertEqual(restored.hash, block.hash)
        self.assertEqual(len(restored.transactions), 1)
        self.assertEqual(restored.transactions[0].txid, block.transactions[0].txid)

    def test_from_wire_hex_roundtrip(self):
        block = make_block()
        restored = Block.from_wire_hex(block.to_bytes().hex())
        self.assertEqual(restored.hash, block.hash)

    def test_hash_changes_with_nonce(self):
        block = make_block()
        h1 = block.hash
        block.header.nonce += 1
        self.assertNotEqual(block.hash, h1)

    def test_merkle_root_mismatch_is_visible(self):
        block = make_block()
        block.header.merkle_root = "0" * 64
        self.assertNotEqual(block.header.merkle_root, block.compute_merkle_root())

    def test_bad_hex_length_rejected(self):
        header = BlockHeader(version=1, prev_hash="00", merkle_root="0" * 64, timestamp=1, target=1, nonce=0)
        with self.assertRaises(Exception):
            header.to_bytes()


if __name__ == "__main__":
    unittest.main()
