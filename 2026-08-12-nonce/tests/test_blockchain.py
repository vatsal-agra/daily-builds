import copy
import unittest

from nonce.wallet import Wallet
from nonce.core.blockchain import Blockchain, create_genesis, subsidy_at
from nonce.core.transaction import Transaction, TxIn, TxOut
from nonce.core.difficulty import RETARGET_INTERVAL


class TestGenesisAndMining(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.genesis = create_genesis(self.alice.address)
        self.chain = Blockchain(self.genesis)

    def test_genesis_pays_subsidy_to_reward_address(self):
        self.assertEqual(self.chain.balance(self.alice.address), subsidy_at(0))
        self.assertEqual(self.chain.height(), 0)

    def test_genesis_meets_its_own_target(self):
        self.assertTrue(self.genesis.header.meets_target())

    def test_mining_extends_chain(self):
        for i in range(3):
            block = self.chain.mine_new_block([], self.alice.address, extra_nonce=i + 1)
            result = self.chain.add_block(block)
            self.assertEqual(result.status, "new_tip")
        self.assertEqual(self.chain.height(), 3)
        self.assertEqual(self.chain.balance(self.alice.address), subsidy_at(0) * 4)

    def test_duplicate_block_rejected(self):
        block = self.chain.mine_new_block([], self.alice.address, extra_nonce=1)
        self.chain.add_block(block)
        result = self.chain.add_block(block)
        self.assertEqual(result.status, "duplicate")

    def test_unknown_parent_buffered_as_orphan(self):
        from nonce.core.block import build_candidate
        from nonce.core.miner import mine
        fake_parent = b"\x99" * 32
        candidate = build_candidate(fake_parent, self.genesis.header.bits,
                                     [Transaction.coinbase(self.alice.address, subsidy_at(1))])
        mine(candidate, max_attempts=500000)
        result = self.chain.add_block(candidate)
        self.assertEqual(result.status, "orphan")


class TestPaymentsAndDoubleSpend(unittest.TestCase):
    def setUp(self):
        self.alice, self.bob = Wallet(), Wallet()
        self.chain = Blockchain(create_genesis(self.alice.address))

    def test_payment_confirms_and_updates_balances(self):
        tx = self.alice.build_transaction(self.chain, self.bob.address, 10_00000000, fee=1000)
        block = self.chain.mine_new_block([tx], self.alice.address, extra_nonce=1)
        result = self.chain.add_block(block)
        self.assertEqual(result.status, "new_tip")
        self.assertEqual(self.chain.balance(self.bob.address), 10_00000000)

    def test_conflicting_mempool_txs_only_one_included(self):
        utxo_key, utxo_val = next(iter(self.chain.utxos_for(self.alice.address).items()))
        tx1 = Transaction([TxIn(*utxo_key)], [TxOut(1_00000000, self.bob.address)])
        tx1.sign_input(0, self.alice.privkey)
        tx2 = Transaction([TxIn(*utxo_key)], [TxOut(1_00000000, self.alice.address)])
        tx2.sign_input(0, self.alice.privkey)

        block = self.chain.mine_new_block([tx1, tx2], self.alice.address, extra_nonce=1)
        non_coinbase = [t for t in block.transactions if not t.is_coinbase()]
        self.assertEqual(len(non_coinbase), 1)
        result = self.chain.add_block(block)
        self.assertEqual(result.status, "new_tip")

    def test_chained_mempool_txs_both_included(self):
        utxo_key, utxo_val = next(iter(self.chain.utxos_for(self.alice.address).items()))
        tx_a = Transaction([TxIn(*utxo_key)],
                            [TxOut(3_00000000, self.bob.address),
                             TxOut(utxo_val.amount - 3_00000000 - 1000, self.alice.address)])
        tx_a.sign_input(0, self.alice.privkey)
        tx_b = Transaction([TxIn(tx_a.txid(), 1)], [TxOut(1_00000000, self.bob.address)])
        tx_b.sign_input(0, self.alice.privkey)

        block = self.chain.mine_new_block([tx_a, tx_b], self.alice.address, extra_nonce=1)
        included_ids = {t.txid() for t in block.transactions}
        self.assertIn(tx_a.txid(), included_ids)
        self.assertIn(tx_b.txid(), included_ids)
        result = self.chain.add_block(block)
        self.assertEqual(result.status, "new_tip")

    def test_direct_double_spend_at_chain_level_rejected(self):
        utxo_key, utxo_val = next(iter(self.chain.utxos_for(self.alice.address).items()))
        tx1 = Transaction([TxIn(*utxo_key)], [TxOut(1_00000000, self.bob.address)])
        tx1.sign_input(0, self.alice.privkey)
        block1 = self.chain.mine_new_block([tx1], self.alice.address, extra_nonce=1)
        self.assertEqual(self.chain.add_block(block1).status, "new_tip")

        tx2 = Transaction([TxIn(*utxo_key)], [TxOut(1_00000000, self.bob.address)])  # same spent input
        tx2.sign_input(0, self.alice.privkey)
        block2 = self.chain.mine_new_block([tx2], self.alice.address, extra_nonce=2)
        non_coinbase = [t for t in block2.transactions if not t.is_coinbase()]
        self.assertEqual(len(non_coinbase), 0, "already-spent input should be filtered from the next template")

    def test_forged_signature_fails_verification(self):
        mallory = Wallet()
        utxo_key, utxo_val = next(iter(self.chain.utxos_for(self.alice.address).items()))
        forged = Transaction([TxIn(*utxo_key)], [TxOut(utxo_val.amount, mallory.address)])
        forged.sign_input(0, mallory.privkey)  # signed with the WRONG key
        self.assertTrue(forged.verify_signatures())  # structurally valid signature...
        block = self.chain.mine_new_block([forged], self.alice.address, extra_nonce=1)
        non_coinbase = [t for t in block.transactions if not t.is_coinbase()]
        self.assertEqual(len(non_coinbase), 0, "signature not matching the UTXO owner must be excluded")


class TestTamperDetection(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.chain = Blockchain(create_genesis(self.alice.address))

    def test_merkle_root_mismatch_rejected(self):
        honest = self.chain.mine_new_block([], self.alice.address, extra_nonce=1)
        tampered = copy.deepcopy(honest)
        tampered.transactions[0].outputs[0].amount += 1
        self.assertEqual(tampered.hash(), honest.hash())  # header untouched by the tamper
        result = self.chain.add_block(tampered)
        self.assertEqual(result.status, "invalid")
        self.assertIn("merkle", result.reason.lower())

    def test_bad_coinbase_reward_rejected(self):
        from nonce.core.block import build_candidate
        from nonce.core.miner import mine
        bad_coinbase = Transaction.coinbase(self.alice.address, subsidy_at(1) + 1)  # +1 sat too much
        candidate = build_candidate(self.chain.tip_hash, self.chain.expected_bits(self.chain.tip_hash),
                                     [bad_coinbase])
        mine(candidate, max_attempts=500000)
        result = self.chain.add_block(candidate)
        self.assertEqual(result.status, "invalid")
        self.assertIn("coinbase reward", result.reason)

    def test_bad_pow_rejected(self):
        block = self.chain.mine_new_block([], self.alice.address, extra_nonce=1)
        block.header.nonce ^= 1  # almost certainly breaks the POW without touching validity of content
        block.header._hash_cache = None
        if block.header.meets_target():
            self.skipTest("flipped nonce coincidentally still meets target (astronomically unlikely)")
        result = self.chain.add_block(block)
        self.assertEqual(result.status, "invalid")

    def test_wrong_difficulty_bits_rejected(self):
        from nonce.core.block import build_candidate
        from nonce.core.miner import mine
        wrong_bits = self.chain.expected_bits(self.chain.tip_hash) - 1  # tiny, essentially-arbitrary change
        candidate = build_candidate(self.chain.tip_hash, wrong_bits,
                                     [Transaction.coinbase(self.alice.address, subsidy_at(1))])
        mine(candidate, max_attempts=500000)
        result = self.chain.add_block(candidate)
        self.assertEqual(result.status, "invalid")
        self.assertIn("difficulty bits", result.reason)


class TestForksAndReorg(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.chain = Blockchain(create_genesis(self.alice.address))
        for i in range(2):
            self.chain.add_block(self.chain.mine_new_block([], self.alice.address, extra_nonce=i + 1))

    def test_heavier_fork_triggers_reorg(self):
        from nonce.core.block import build_candidate
        from nonce.core.miner import mine

        fork_point = self.chain.tip_hash
        fork_height = self.chain.height()

        def mine_on(prev_hash, height, extra_nonce):
            # distinct extra_nonce per branch, exactly like Node.mine_block does — two
            # miners racing to extend the same parent at the same timestamp would
            # otherwise build byte-identical coinbases and mine the literal same block
            bits = self.chain.expected_bits(prev_hash)
            cb = Transaction.coinbase(self.alice.address, subsidy_at(height), extra_nonce=extra_nonce)
            candidate = build_candidate(prev_hash, bits, [cb])
            return mine(candidate)

        block_a = mine_on(fork_point, fork_height + 1, extra_nonce=1)
        self.chain.add_block(block_a)  # branch A: +1

        b1 = mine_on(fork_point, fork_height + 1, extra_nonce=2)  # branch B's 1st block: ties A on work
        result1 = self.chain.add_block(b1)
        # A tie in cumulative work is resolved deterministically by hash (see REVIEW.md
        # finding #6), NOT always "loses to whichever arrived first" — so either outcome
        # is valid here, as long as the tip is exactly whichever hash is lower.
        self.assertIn(result1.status, ("new_tip", "side_branch"))
        self.assertEqual(self.chain.tip_hash, min(block_a.hash(), b1.hash()))

        b2 = mine_on(b1.hash(), fork_height + 2, extra_nonce=3)  # branch B's 2nd block: strictly more work now
        result2 = self.chain.add_block(b2)
        self.assertEqual(result2.status, "new_tip")
        self.assertEqual(self.chain.tip_hash, b2.hash())

    def test_equal_work_fork_breaks_tie_deterministically(self):
        from nonce.core.block import build_candidate
        from nonce.core.miner import mine

        fork_point = self.chain.tip_hash
        bits = self.chain.expected_bits(fork_point)

        def mine_variant(extra_nonce):
            cb = Transaction.coinbase(self.alice.address, subsidy_at(self.chain.height() + 1), extra_nonce=extra_nonce)
            candidate = build_candidate(fork_point, bits, [cb])
            return mine(candidate)

        block_x = mine_variant(1)
        block_y = mine_variant(2)
        self.assertNotEqual(block_x.hash(), block_y.hash())

        # replaying in either order must land on the same, lower-hash winner
        winner = min(block_x.hash(), block_y.hash())

        chain_a = Blockchain(copy.deepcopy(self.chain.blocks[self.chain.genesis_hash]))
        for h in self.chain.chain_to_genesis(fork_point)[1:]:
            chain_a.add_block(copy.deepcopy(self.chain.blocks[h]))
        chain_a.add_block(copy.deepcopy(block_x))
        chain_a.add_block(copy.deepcopy(block_y))

        chain_b = Blockchain(copy.deepcopy(self.chain.blocks[self.chain.genesis_hash]))
        for h in self.chain.chain_to_genesis(fork_point)[1:]:
            chain_b.add_block(copy.deepcopy(self.chain.blocks[h]))
        chain_b.add_block(copy.deepcopy(block_y))
        chain_b.add_block(copy.deepcopy(block_x))

        self.assertEqual(chain_a.tip_hash, winner)
        self.assertEqual(chain_b.tip_hash, winner)
        self.assertEqual(chain_a.tip_hash, chain_b.tip_hash, "tie-break must be order-independent")


class TestDifficultyRetargetIntegration(unittest.TestCase):
    def test_difficulty_changes_over_a_retarget_window(self):
        alice = Wallet()
        chain = Blockchain(create_genesis(alice.address))
        bits_seen = []
        for i in range(RETARGET_INTERVAL + 2):
            block = chain.mine_new_block([], alice.address, extra_nonce=i + 1)
            result = chain.add_block(block)
            self.assertEqual(result.status, "new_tip")
            bits_seen.append(block.header.bits)
        self.assertGreater(len(set(bits_seen)), 1, "difficulty should have retargeted at least once")


class TestSupplyInvariant(unittest.TestCase):
    def test_total_utxo_value_matches_expected_subsidy_sum(self):
        alice, bob = Wallet(), Wallet()
        chain = Blockchain(create_genesis(alice.address))
        for i in range(5):
            block = chain.mine_new_block([], alice.address, extra_nonce=i + 1)
            chain.add_block(block)
        tx = alice.build_transaction(chain, bob.address, 5_00000000, fee=2000)
        block = chain.mine_new_block([tx], alice.address, extra_nonce=99)
        chain.add_block(block)

        total_supply = sum(o.amount for o in chain.utxo_set.values())
        expected = sum(subsidy_at(h) for h in range(chain.height() + 1))
        self.assertEqual(total_supply, expected, "fees move value around but never create or destroy it")


if __name__ == "__main__":
    unittest.main()
