import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import block as blk
import crypto as c
import transaction as tx


def sample_coinbase(kp, height=0):
    return tx.Transaction.coinbase(c.hash160(kp.pubkey_bytes()), reward=5000, height=height)


class TestMining(unittest.TestCase):
    def test_mined_block_meets_target(self):
        kp = c.KeyPair.generate()
        target = blk.MAX_TARGET >> 12
        b = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[sample_coinbase(kp)], target=target)
        nonce = b.mine()
        self.assertIsNotNone(nonce)
        self.assertTrue(b.is_valid_pow())
        self.assertLessEqual(int.from_bytes(b.block_hash(), "big"), target)

    def test_mining_exhaustion_returns_none(self):
        kp = c.KeyPair.generate()
        target = 0  # impossible target (only hash==0 would satisfy it)
        b = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[sample_coinbase(kp)], target=target)
        nonce = b.mine(max_nonce=200)
        self.assertIsNone(nonce)

    def test_serialize_roundtrip(self):
        kp = c.KeyPair.generate()
        b = blk.Block.new(prev_hash=b"\x11" * 32, transactions=[sample_coinbase(kp)], target=blk.MAX_TARGET >> 8)
        b.mine()
        raw = b.serialize()
        b2, off = blk.Block.deserialize(raw)
        self.assertEqual(off, len(raw))
        self.assertEqual(b2.block_hash(), b.block_hash())
        self.assertEqual(len(b2.transactions), 1)
        self.assertEqual(b2.transactions[0].txid(), b.transactions[0].txid())

    def test_tampering_transaction_breaks_merkle_root(self):
        kp = c.KeyPair.generate()
        b = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[sample_coinbase(kp)], target=blk.MAX_TARGET >> 8)
        b.mine()
        original_root = b.header.merkle_root
        b.transactions[0].outputs[0].amount += 1
        self.assertNotEqual(b.compute_merkle_root(), original_root)

    def test_multi_tx_merkle_root_matches_standalone_computation(self):
        import merkle as m
        kp = c.KeyPair.generate()
        txs = [sample_coinbase(kp)] + [
            tx.Transaction(inputs=[tx.TxIn(c.hash256(str(i).encode()), 0, kp.pubkey_bytes())],
                           outputs=[tx.TxOut(1, b"\x00" * 20)])
            for i in range(4)
        ]
        b = blk.Block.new(prev_hash=b"\x00" * 32, transactions=txs, target=blk.MAX_TARGET >> 4)
        expected = m.merkle_root([t.txid() for t in txs])
        self.assertEqual(b.header.merkle_root, expected)


if __name__ == "__main__":
    unittest.main()
