import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import block as blk
import blockchain as bc
import crypto as c
import transaction as tx
from helpers import make_genesis, mine_on_top


class TestGenesisAndBasicChain(unittest.TestCase):
    def setUp(self):
        self.genesis = make_genesis()
        self.chain = bc.Blockchain(self.genesis)

    def test_genesis_state(self):
        self.assertEqual(self.chain.height(), 0)
        self.assertEqual(self.chain.tip, self.genesis.block_hash())
        self.assertEqual(len(self.chain.utxo_set()), 1)

    def test_extend_chain_by_one_block(self):
        alice = c.KeyPair.generate()
        cb = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        b1 = mine_on_top(self.chain, self.chain.genesis_hash, [cb], 1_000_001)
        res = self.chain.accept_block(b1)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(self.chain.height(), 1)
        self.assertIn((cb.txid(), 0), self.chain.utxo_set())


class TestGenesisValidation(unittest.TestCase):
    """Regression coverage for a Phase 3 finding: the genesis block used to
    get no PoW/merkle-root validation at all -- an unmined or tampered
    genesis would be silently accepted, breaking the chain's security model
    from block zero."""

    def test_unmined_genesis_rejected(self):
        cb = tx.Transaction.coinbase(b"\x00" * 20, reward=bc.subsidy_at(0), height=0)
        g = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[cb], target=bc.GENESIS_TARGET_DEFAULT,
                           timestamp=1_000_000)
        # deliberately not mined -- nonce=0 essentially never meets a real target
        with self.assertRaises(bc.ChainError):
            bc.Blockchain(g)

    def test_tampered_merkle_root_genesis_rejected(self):
        g = make_genesis()
        g.header.merkle_root = c.hash256(b"forged")
        with self.assertRaises(bc.ChainError):
            bc.Blockchain(g)

    def test_properly_mined_genesis_accepted(self):
        g = make_genesis()
        chain = bc.Blockchain(g)
        self.assertEqual(chain.height(), 0)


class TestBlockRejection(unittest.TestCase):
    def setUp(self):
        self.genesis = make_genesis()
        self.chain = bc.Blockchain(self.genesis)
        self.alice = c.KeyPair.generate()

    def _valid_next_block(self, ts=1_000_001):
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        return mine_on_top(self.chain, self.chain.genesis_hash, [cb], ts)

    def test_unknown_parent_is_buffered_as_orphan(self):
        fake_parent = c.hash256(b"nonexistent")
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        b = blk.Block.new(prev_hash=fake_parent, transactions=[cb], target=self.chain.next_expected_target(),
                           timestamp=1_000_001)
        b.mine()
        res = self.chain.accept_block(b)
        self.assertFalse(res.accepted)
        self.assertIn("orphan", res.reason)
        self.assertEqual(self.chain.height(), 0)  # chain state unaffected

    def test_orphan_attaches_once_parent_arrives(self):
        b1 = self._valid_next_block(1_000_001)
        # b1 is not yet known to the chain, so target for the block built on
        # top of it can't be asked of `chain` (it doesn't know that height
        # yet) -- reuse the same target, valid since height 2 is still inside
        # height 1's retarget window.
        same_target = self.chain.next_expected_target()
        cb2 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(2), height=2)
        b2 = mine_on_top(self.chain, b1.block_hash(), [cb2], 1_000_002, target=same_target)
        # submit the CHILD before the PARENT is known
        res_child_first = self.chain.accept_block(b2)
        self.assertFalse(res_child_first.accepted)
        self.assertIn("orphan", res_child_first.reason)
        res_parent = self.chain.accept_block(b1)
        self.assertTrue(res_parent.accepted)
        # parent's acceptance should have pulled the buffered child in automatically
        self.assertEqual(self.chain.height(), 2)
        self.assertEqual(self.chain.tip, b2.block_hash())

    def test_wrong_difficulty_target_rejected(self):
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        wrong_target = self.chain.next_expected_target() // 2
        b = blk.Block.new(prev_hash=self.chain.genesis_hash, transactions=[cb], target=wrong_target,
                           timestamp=1_000_001)
        b.mine()
        res = self.chain.accept_block(b)
        self.assertFalse(res.accepted)
        self.assertIn("difficulty", res.reason)

    def test_pow_not_met_rejected(self):
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        b = blk.Block.new(prev_hash=self.chain.genesis_hash, transactions=[cb],
                           target=self.chain.next_expected_target(), timestamp=1_000_001)
        # deliberately do NOT mine: nonce=0 essentially never meets a real target
        res = self.chain.accept_block(b)
        self.assertFalse(res.accepted)
        self.assertIn("target", res.reason)

    def test_bad_merkle_root_rejected(self):
        b = self._valid_next_block()
        b.header.merkle_root = c.hash256(b"forged-root")
        # Re-mine by hand (not Block.mine(), which would recompute the
        # correct root from the real transactions before searching nonces)
        # so PoW passes against the *forged* root, isolating the merkle
        # check from the PoW check.
        nonce = 0
        while not b.header.meets_target():
            b.header.nonce = nonce
            nonce += 1
            if nonce > 2_000_000:
                self.fail("could not re-mine with forged root within budget")
        res = self.chain.accept_block(b)
        self.assertFalse(res.accepted)
        self.assertIn("merkle", res.reason)

    def test_missing_coinbase_rejected(self):
        alice2 = c.KeyPair.generate()
        prevout_lookup_tx = tx.Transaction(
            inputs=[tx.TxIn(prev_txid=c.hash256(b"phantom"), prev_index=0, pubkey=alice2.pubkey_bytes())],
            outputs=[tx.TxOut(1, c.hash160(alice2.pubkey_bytes()))],
        )
        prevout_lookup_tx.sign_input(0, alice2.private_key)
        b = mine_on_top(self.chain, self.chain.genesis_hash, [prevout_lookup_tx], 1_000_001)
        res = self.chain.accept_block(b)
        self.assertFalse(res.accepted)
        self.assertIn("coinbase", res.reason)

    def test_coinbase_overclaim_rejected(self):
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(1) + 1, height=1)
        b = mine_on_top(self.chain, self.chain.genesis_hash, [cb], 1_000_001)
        res = self.chain.accept_block(b)
        self.assertFalse(res.accepted)
        self.assertIn("coinbase claims", res.reason)

    def test_future_timestamp_rejected(self):
        cb = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        far_future = int(__import__("time").time()) + bc.MAX_FUTURE_DRIFT + 1000
        b = blk.Block.new(prev_hash=self.chain.genesis_hash, transactions=[cb],
                           target=self.chain.next_expected_target(), timestamp=far_future)
        b.mine()
        res = self.chain.accept_block(b, now=int(__import__("time").time()))
        self.assertFalse(res.accepted)
        self.assertIn("future", res.reason)

    def test_non_increasing_timestamp_rejected(self):
        b1 = self._valid_next_block(1_000_001)
        self.chain.accept_block(b1)
        cb2 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(2), height=2)
        b2 = blk.Block.new(prev_hash=b1.block_hash(), transactions=[cb2],
                            target=self.chain.next_expected_target(), timestamp=1_000_000)  # <= genesis ts
        b2.mine()
        res = self.chain.accept_block(b2)
        self.assertFalse(res.accepted)
        self.assertIn("median", res.reason)

    def test_duplicate_block_rejected(self):
        b1 = self._valid_next_block()
        res1 = self.chain.accept_block(b1)
        self.assertTrue(res1.accepted)
        res2 = self.chain.accept_block(b1)
        self.assertFalse(res2.accepted)
        self.assertIn("duplicate", res2.reason)


class TestDoubleSpendAndSpending(unittest.TestCase):
    def setUp(self):
        self.genesis = make_genesis()
        self.chain = bc.Blockchain(self.genesis)
        self.alice = c.KeyPair.generate()
        self.bob = c.KeyPair.generate()
        cb1 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        self.b1 = mine_on_top(self.chain, self.chain.genesis_hash, [cb1], 1_000_001)
        res = self.chain.accept_block(self.b1)
        assert res.accepted
        self.alice_outpoint = (cb1.txid(), 0)
        self.alice_amount = cb1.total_output()

    def _spend_alice_outpoint(self, amount, dest_kp):
        t = tx.Transaction(
            inputs=[tx.TxIn(prev_txid=self.alice_outpoint[0], prev_index=0, pubkey=self.alice.pubkey_bytes())],
            outputs=[tx.TxOut(amount=amount, pubkey_hash=c.hash160(dest_kp.pubkey_bytes()))],
        )
        t.sign_input(0, self.alice.private_key)
        return t

    def test_confirmed_spend_moves_value(self):
        spend = self._spend_alice_outpoint(self.alice_amount - 1000, self.bob)
        cb2 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(2) + 1000, height=2)
        b2 = mine_on_top(self.chain, self.b1.block_hash(), [cb2, spend], 1_000_002)
        res = self.chain.accept_block(b2)
        self.assertTrue(res.accepted, res.reason)
        self.assertNotIn(self.alice_outpoint, self.chain.utxo_set())
        self.assertIn((spend.txid(), 0), self.chain.utxo_set())

    def test_spend_of_already_confirmed_output_rejected_in_later_block(self):
        spend = self._spend_alice_outpoint(self.alice_amount - 1000, self.bob)
        cb2 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(2) + 1000, height=2)
        b2 = mine_on_top(self.chain, self.b1.block_hash(), [cb2, spend], 1_000_002)
        self.chain.accept_block(b2)

        respend = self._spend_alice_outpoint(1, self.bob)
        cb3 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(3), height=3)
        b3 = mine_on_top(self.chain, b2.block_hash(), [cb3, respend], 1_000_003)
        res3 = self.chain.accept_block(b3)
        self.assertFalse(res3.accepted)
        self.assertIn("missing/spent", res3.reason)

    def test_in_block_double_spend_rejected(self):
        spend_a = self._spend_alice_outpoint(1, self.bob)
        spend_b = self._spend_alice_outpoint(2, self.bob)
        cb2 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(2), height=2)
        b2 = mine_on_top(self.chain, self.b1.block_hash(), [cb2, spend_a, spend_b], 1_000_002)
        res = self.chain.accept_block(b2)
        self.assertFalse(res.accepted)
        self.assertIn("missing/spent", res.reason)

    def test_chained_spend_within_same_block_allowed(self):
        # spend_a creates an output that spend_b immediately consumes, both in
        # the same block -- a real chain permits this (it's not a conflict).
        change = self.alice_amount - 2000
        spend_a = tx.Transaction(
            inputs=[tx.TxIn(prev_txid=self.alice_outpoint[0], prev_index=0, pubkey=self.alice.pubkey_bytes())],
            outputs=[tx.TxOut(amount=change, pubkey_hash=c.hash160(self.alice.pubkey_bytes()))],
        )
        spend_a.sign_input(0, self.alice.private_key)
        spend_b = tx.Transaction(
            inputs=[tx.TxIn(prev_txid=spend_a.txid(), prev_index=0, pubkey=self.alice.pubkey_bytes())],
            outputs=[tx.TxOut(amount=change - 1000, pubkey_hash=c.hash160(self.bob.pubkey_bytes()))],
        )
        spend_b.sign_input(0, self.alice.private_key)
        cb2 = tx.Transaction.coinbase(c.hash160(self.alice.pubkey_bytes()), reward=bc.subsidy_at(2) + 2000, height=2)
        b2 = mine_on_top(self.chain, self.b1.block_hash(), [cb2, spend_a, spend_b], 1_000_002)
        res = self.chain.accept_block(b2)
        self.assertTrue(res.accepted, res.reason)
        self.assertIn((spend_b.txid(), 0), self.chain.utxo_set())
        self.assertNotIn((spend_a.txid(), 0), self.chain.utxo_set())  # consumed within the same block


class TestDifficultyRetargeting(unittest.TestCase):
    def test_fast_blocks_increase_difficulty(self):
        genesis = make_genesis()
        chain = bc.Blockchain(genesis)
        alice = c.KeyPair.generate()
        prev = chain.genesis_hash
        ts = 1_000_000
        targets = [chain.blocks[prev].header.target]
        for i in range(1, 11):
            ts += 1  # far faster than TARGET_BLOCK_TIME=2s
            cb = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(i), height=i)
            b = mine_on_top(chain, prev, [cb], ts)
            res = chain.accept_block(b)
            assert res.accepted, res.reason
            targets.append(b.header.target)
            prev = b.block_hash()
        self.assertLess(targets[10], targets[0])  # harder (lower target) after the fast window

    def test_slow_blocks_decrease_difficulty(self):
        genesis = make_genesis()
        chain = bc.Blockchain(genesis)
        alice = c.KeyPair.generate()
        prev = chain.genesis_hash
        ts = 1_000_000
        targets = [chain.blocks[prev].header.target]
        for i in range(1, 11):
            ts += 100  # far slower than TARGET_BLOCK_TIME=2s
            cb = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(i), height=i)
            b = mine_on_top(chain, prev, [cb], ts)
            res = chain.accept_block(b)
            assert res.accepted, res.reason
            targets.append(b.header.target)
            prev = b.block_hash()
        self.assertGreater(targets[10], targets[0])  # easier (higher target) after the slow window

    def test_retarget_clamped_to_max_factor(self):
        genesis = make_genesis()
        chain = bc.Blockchain(genesis)
        alice = c.KeyPair.generate()
        prev = chain.genesis_hash
        ts = 1_000_000
        for i in range(1, 10):
            ts += 1
            cb = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(i), height=i)
            b = mine_on_top(chain, prev, [cb], ts)
            chain.accept_block(b)
            prev = b.block_hash()
        ts += 1_000_000  # absurdly slow last block in the window
        cb = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(10), height=10)
        target_before = chain.blocks[prev].header.target
        expected = chain._expected_target(prev)
        self.assertLessEqual(expected, int(target_before * bc.MAX_RETARGET_FACTOR) + 1)


class TestForkAndReorg(unittest.TestCase):
    def test_reorg_onto_more_work_chain(self):
        genesis = make_genesis()
        chain = bc.Blockchain(genesis)
        alice = c.KeyPair.generate()
        bob = c.KeyPair.generate()
        ts = 1_000_000

        cb1 = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        b1 = mine_on_top(chain, chain.genesis_hash, [cb1], ts + 1)
        self.assertTrue(chain.accept_block(b1).accepted)
        fork_point = b1.block_hash()

        target2 = chain._expected_target(fork_point)
        cb2a = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(2), height=2)
        b2a = mine_on_top(chain, fork_point, [cb2a], ts + 2, target=target2)
        cb2b = tx.Transaction.coinbase(c.hash160(bob.pubkey_bytes()), reward=bc.subsidy_at(2), height=2)
        b2b = mine_on_top(chain, fork_point, [cb2b], ts + 2, target=target2)

        res_a = chain.accept_block(b2a)
        self.assertTrue(res_a.accepted)
        self.assertEqual(chain.tip, b2a.block_hash())

        res_b = chain.accept_block(b2b)
        self.assertTrue(res_b.accepted)          # valid side branch...
        self.assertFalse(res_b.reorged)
        self.assertEqual(chain.tip, b2a.block_hash())  # ...but a tie doesn't move the tip

        target3 = chain._expected_target(b2b.block_hash())
        cb3b = tx.Transaction.coinbase(c.hash160(bob.pubkey_bytes()), reward=bc.subsidy_at(3), height=3)
        b3b = mine_on_top(chain, b2b.block_hash(), [cb3b], ts + 3, target=target3)
        res3b = chain.accept_block(b3b)
        self.assertTrue(res3b.accepted, res3b.reason)
        self.assertTrue(res3b.reorged)
        self.assertEqual(chain.tip, b3b.block_hash())
        self.assertEqual(chain.height(), 3)

        u = chain.utxo_set()
        self.assertNotIn((cb2a.txid(), 0), u, "losing fork's coinbase must be undone")
        self.assertIn((cb2b.txid(), 0), u, "winning fork's coinbase must be applied")
        self.assertIn((cb3b.txid(), 0), u)
        self.assertIn((cb1.txid(), 0), u, "common ancestor state must be untouched")
        self.assertEqual(len(chain.main_chain_hashes()), 4)

    def test_spend_confirmed_only_on_losing_fork_disappears_after_reorg(self):
        genesis = make_genesis()
        chain = bc.Blockchain(genesis)
        alice = c.KeyPair.generate()
        bob = c.KeyPair.generate()
        ts = 1_000_000

        cb1 = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(1), height=1)
        b1 = mine_on_top(chain, chain.genesis_hash, [cb1], ts + 1)
        chain.accept_block(b1)
        fork_point = b1.block_hash()

        # Fork A: alice spends her own coinbase to bob
        spend = tx.Transaction(
            inputs=[tx.TxIn(cb1.txid(), 0, alice.pubkey_bytes())],
            outputs=[tx.TxOut(cb1.total_output() - 1000, c.hash160(bob.pubkey_bytes()))],
        )
        spend.sign_input(0, alice.private_key)
        target2 = chain._expected_target(fork_point)
        cb2a = tx.Transaction.coinbase(c.hash160(alice.pubkey_bytes()), reward=bc.subsidy_at(2) + 1000, height=2)
        b2a = mine_on_top(chain, fork_point, [cb2a, spend], ts + 2, target=target2)
        chain.accept_block(b2a)
        self.assertIn((spend.txid(), 0), chain.utxo_set())

        # Fork B: does NOT include that spend, and gets 2 blocks of work vs fork A's 1
        cb2b = tx.Transaction.coinbase(c.hash160(bob.pubkey_bytes()), reward=bc.subsidy_at(2), height=2)
        b2b = mine_on_top(chain, fork_point, [cb2b], ts + 2, target=target2)
        chain.accept_block(b2b)
        target3 = chain._expected_target(b2b.block_hash())
        cb3b = tx.Transaction.coinbase(c.hash160(bob.pubkey_bytes()), reward=bc.subsidy_at(3), height=3)
        b3b = mine_on_top(chain, b2b.block_hash(), [cb3b], ts + 3, target=target3)
        res = chain.accept_block(b3b)
        self.assertTrue(res.reorged)

        u = chain.utxo_set()
        self.assertNotIn((spend.txid(), 0), u, "a tx only confirmed on the losing fork must vanish")
        self.assertIn((cb1.txid(), 0), u, "alice's original coinbase is unspent again on the winning fork")


if __name__ == "__main__":
    unittest.main()
