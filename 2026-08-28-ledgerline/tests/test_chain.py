import time
import unittest

from ledgerline.block import Block, BlockHeader, mine_block, make_genesis_block
from ledgerline.chain import BLOCK_REWARD, MAX_RETARGET_FACTOR, RETARGET_INTERVAL, Blockchain
from ledgerline.transaction import build_transaction, make_coinbase
from ledgerline.wallet import Wallet

BITS = 10
RETARGET_BITS = 6  # cheap enough to mine RETARGET_INTERVAL+ real blocks fast in a test


def mined(prev_hash, height, txs, bits=BITS):
    header = BlockHeader(1, prev_hash, "", time.time(), bits, 0, height)
    block = Block(header, txs)
    header.merkle_root_hex = block.compute_merkle_root()
    mine_block(block, stop_flag=lambda: False)
    return block


class ChainTestBase(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()
        self.carol = Wallet()
        self.cb = make_coinbase(self.alice.address, 1000, height=0)
        self.genesis = make_genesis_block(self.cb, bits=BITS)
        self.chain = Blockchain()
        ok, msg, _ = self.chain.add_block(self.genesis, BITS)
        assert ok, msg


class TestBasicChain(ChainTestBase):
    def test_genesis_funds_alice(self):
        self.assertEqual(self.chain.balance_of(self.alice.address), 1000)

    def test_simple_spend(self):
        utxos = self.chain.utxos_for(self.alice.address)
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        b1 = mined(self.genesis.hash_hex(), 1, [cb1, tx])
        ok, msg, _ = self.chain.add_block(b1, BITS)
        self.assertTrue(ok, msg)
        self.assertEqual(self.chain.balance_of(self.alice.address), 899)
        self.assertEqual(self.chain.balance_of(self.bob.address), 100 + BLOCK_REWARD)

    def test_double_spend_within_block_rejected(self):
        utxos = self.chain.utxos_for(self.alice.address)
        tx1 = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 1, self.alice.address)
        tx2 = build_transaction(utxos, self.alice.privkey, self.carol.address, 200, 1, self.alice.address)
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        b1 = mined(self.genesis.hash_hex(), 1, [cb1, tx1, tx2])
        ok, msg, _ = self.chain.add_block(b1, BITS)
        self.assertFalse(ok)
        self.assertIn("double-spend", msg)

    def test_spending_someone_elses_utxo_rejected(self):
        alice_utxos = self.chain.utxos_for(self.alice.address)
        # bob signs a transaction "spending" alice's utxo
        tx = build_transaction(alice_utxos, self.bob.privkey, self.carol.address, 100, 1, self.bob.address)
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        b1 = mined(self.genesis.hash_hex(), 1, [cb1, tx])
        ok, msg, _ = self.chain.add_block(b1, BITS)
        self.assertFalse(ok)

    def test_overspend_rejected(self):
        utxos = self.chain.utxos_for(self.alice.address)
        with self.assertRaises(ValueError):
            build_transaction(utxos, self.alice.privkey, self.bob.address, 10**9, 1, self.alice.address)

    def test_coinbase_claiming_too_much_rejected(self):
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD + 1000, height=1)
        b1 = mined(self.genesis.hash_hex(), 1, [cb1])
        ok, msg, _ = self.chain.add_block(b1, BITS)
        self.assertFalse(ok)
        self.assertIn("coinbase", msg)

    def test_coinbase_may_claim_reward_plus_fees(self):
        utxos = self.chain.utxos_for(self.alice.address)
        tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 100, 5, self.alice.address)
        cb1 = make_coinbase(self.carol.address, BLOCK_REWARD + 5, height=1)
        b1 = mined(self.genesis.hash_hex(), 1, [cb1, tx])
        ok, msg, _ = self.chain.add_block(b1, BITS)
        self.assertTrue(ok, msg)
        self.assertEqual(self.chain.balance_of(self.carol.address), BLOCK_REWARD + 5)

    def test_wrong_height_rejected(self):
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=99)
        b1 = mined(self.genesis.hash_hex(), 99, [cb1])
        ok, msg, _ = self.chain.add_block(b1, BITS)
        self.assertFalse(ok)
        self.assertIn("height", msg)

    def test_unknown_parent_is_orphan(self):
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        b1 = mined("f" * 64, 1, [cb1])
        ok, msg, _ = self.chain.add_block(b1, BITS)
        self.assertFalse(ok)
        self.assertIn("orphan", msg)

    def test_already_known_block_rejected_second_time(self):
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        b1 = mined(self.genesis.hash_hex(), 1, [cb1])
        ok1, _, _ = self.chain.add_block(b1, BITS)
        ok2, msg2, _ = self.chain.add_block(b1, BITS)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("already known", msg2)


class TestReorg(ChainTestBase):
    def test_higher_work_side_branch_triggers_reorg(self):
        cb_a = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        # note: with retargeting disabled (Phase 2), every block must carry
        # the same `bits` as genesis — a block can't unilaterally claim a
        # different difficulty. So "more cumulative work" here has to come
        # from a genuinely longer branch (2 blocks beats 1), exactly like
        # a real competing miner racing ahead, not from a hand-picked bits
        # value (that was this test's original, invalid, approach).
        block_a = mined(self.genesis.hash_hex(), 1, [cb_a], bits=BITS)
        ok, _, _ = self.chain.add_block(block_a, BITS)
        self.assertTrue(ok)
        self.assertEqual(self.chain.tip, block_a.hash_hex())

        # a competing branch off genesis that races two blocks deep ->
        # more cumulative work -> must win even though we saw it second
        cb_b1 = make_coinbase(self.carol.address, BLOCK_REWARD, height=1)
        block_b1 = mined(self.genesis.hash_hex(), 1, [cb_b1], bits=BITS)
        cb_b2 = make_coinbase(self.carol.address, BLOCK_REWARD, height=2)
        block_b2 = mined(block_b1.hash_hex(), 2, [cb_b2], bits=BITS)

        ok, msg, reorg = self.chain.add_block(block_b1, BITS)
        self.assertTrue(ok)
        self.assertEqual(msg, "stored as side branch (insufficient work to reorg)")
        self.assertEqual(self.chain.tip, block_a.hash_hex(), "1 block of work must not beat 1 block of work")

        ok, msg, reorg = self.chain.add_block(block_b2, BITS)
        self.assertTrue(ok)
        self.assertEqual(msg, "reorg")
        self.assertEqual(self.chain.tip, block_b2.hash_hex())
        # bob's reward from the losing block must be gone
        self.assertEqual(self.chain.balance_of(self.bob.address), 0)
        self.assertEqual(self.chain.balance_of(self.carol.address), 2 * BLOCK_REWARD)

    def test_lower_work_side_branch_does_not_reorg(self):
        cb_a1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        block_a1 = mined(self.genesis.hash_hex(), 1, [cb_a1], bits=BITS)
        self.chain.add_block(block_a1, BITS)
        cb_a2 = make_coinbase(self.bob.address, BLOCK_REWARD, height=2)
        block_a2 = mined(block_a1.hash_hex(), 2, [cb_a2], bits=BITS)
        self.chain.add_block(block_a2, BITS)
        original_tip = self.chain.tip
        self.assertEqual(original_tip, block_a2.hash_hex())

        cb_b = make_coinbase(self.carol.address, BLOCK_REWARD, height=1)
        block_b = mined(self.genesis.hash_hex(), 1, [cb_b], bits=BITS)
        ok, msg, reorg = self.chain.add_block(block_b, BITS)
        self.assertTrue(ok)
        self.assertIsNone(reorg)
        self.assertEqual(self.chain.tip, original_tip)

    def test_disconnected_transaction_becomes_spendable_again(self):
        # spend alice's premine utxo in the losing (1-block) branch
        utxos = self.chain.utxos_for(self.alice.address)
        spend_tx = build_transaction(utxos, self.alice.privkey, self.bob.address, 500, 1, self.alice.address)
        cb_a = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        block_a = mined(self.genesis.hash_hex(), 1, [cb_a, spend_tx], bits=BITS)
        self.chain.add_block(block_a, BITS)
        self.assertEqual(self.chain.balance_of(self.alice.address), 1000 - 500 - 1)

        # a heavier (2-block) competing branch that does NOT include the spend
        cb_b1 = make_coinbase(self.carol.address, BLOCK_REWARD, height=1)
        block_b1 = mined(self.genesis.hash_hex(), 1, [cb_b1], bits=BITS)
        self.chain.add_block(block_b1, BITS)
        cb_b2 = make_coinbase(self.carol.address, BLOCK_REWARD, height=2)
        block_b2 = mined(block_b1.hash_hex(), 2, [cb_b2], bits=BITS)
        ok, msg, reorg = self.chain.add_block(block_b2, BITS)
        self.assertTrue(ok)
        self.assertEqual(msg, "reorg")
        # alice's original utxo must be spendable again on the new active chain
        self.assertEqual(self.chain.balance_of(self.alice.address), 1000)
        self.assertEqual(len(reorg["disconnected_txs"]), 1)
        self.assertEqual(reorg["disconnected_txs"][0].txid(), spend_tx.txid())


class TestDifficultyRetargeting(unittest.TestCase):
    """Direct, deterministic coverage of calc_next_bits — real mined
    blocks (so PoW validation is genuinely exercised), fake timestamps
    (so the test doesn't depend on wall-clock timing or real hashrate)."""

    def setUp(self):
        self.alice = Wallet()
        self.cb = make_coinbase(self.alice.address, 1000, height=0)
        self.genesis = make_genesis_block(self.cb, bits=RETARGET_BITS)
        self.chain = Blockchain(retarget_enabled=True)
        ok, msg, _ = self.chain.add_block(self.genesis, RETARGET_BITS)
        assert ok, msg

    def _mine_one(self, ts) -> None:
        parent = self.chain.tip
        height = self.chain.height() + 1
        bits = self.chain.calc_next_bits(parent, RETARGET_BITS)
        cb = make_coinbase(self.alice.address, BLOCK_REWARD, height=height)
        header = BlockHeader(1, parent, "", ts, bits, 0, height)
        block = Block(header, [cb])
        header.merkle_root_hex = block.compute_merkle_root()
        found = mine_block(block, stop_flag=lambda: False)
        assert found
        ok, msg, _ = self.chain.add_block(block, RETARGET_BITS)
        assert ok, msg

    def _mine_period(self, timestamps) -> None:
        assert len(timestamps) == RETARGET_INTERVAL
        for ts in timestamps:
            self._mine_one(ts)

    def test_disabled_by_default_stays_fixed(self):
        fresh = Blockchain(retarget_enabled=False)
        fresh.add_block(self.genesis, RETARGET_BITS)
        self.assertEqual(fresh.calc_next_bits(fresh.tip, RETARGET_BITS), RETARGET_BITS)

    def test_no_change_before_a_full_interval(self):
        # blocks 1..RETARGET_INTERVAL-1, even mined absurdly fast, must
        # each still carry the fixed genesis bits — only the block at
        # height RETARGET_INTERVAL, which completes a full window, is
        # allowed to change it (checked separately by the "faster/slower"
        # tests above).
        for i in range(1, RETARGET_INTERVAL):
            self._mine_one(i * 0.001)
            self.assertEqual(self.chain.blocks[self.chain.tip].header.bits, RETARGET_BITS)

    def test_faster_than_target_increases_difficulty(self):
        # RETARGET_INTERVAL blocks packed into a tiny real timespan -> way
        # faster than RETARGET_TIMESPAN_SECONDS -> bits must go UP (harder)
        timestamps = [i * 0.01 for i in range(1, RETARGET_INTERVAL + 1)]
        self._mine_period(timestamps)
        new_bits = self.chain.calc_next_bits(self.chain.tip, RETARGET_BITS)
        self.assertGreater(new_bits, RETARGET_BITS)

    def test_slower_than_target_decreases_difficulty(self):
        # RETARGET_INTERVAL blocks spread over a huge timespan -> way
        # slower than target -> bits must go DOWN (easier)
        timestamps = [i * 1000.0 for i in range(1, RETARGET_INTERVAL + 1)]
        self._mine_period(timestamps)
        new_bits = self.chain.calc_next_bits(self.chain.tip, RETARGET_BITS)
        self.assertLess(new_bits, RETARGET_BITS)

    def test_single_adjustment_clamped_to_max_factor(self):
        # an absurdly fast period must not swing difficulty by more than
        # log2(MAX_RETARGET_FACTOR) bits in one retarget
        timestamps = [i * 0.0001 for i in range(1, RETARGET_INTERVAL + 1)]
        self._mine_period(timestamps)
        new_bits = self.chain.calc_next_bits(self.chain.tip, RETARGET_BITS)
        import math
        self.assertLessEqual(new_bits - RETARGET_BITS, round(math.log2(MAX_RETARGET_FACTOR)))

    def test_more_hashrate_over_two_periods_ratchets_difficulty_up(self):
        # two consecutive fast periods should each independently push
        # difficulty higher, not just the first one
        fast = [i * 0.01 for i in range(1, RETARGET_INTERVAL + 1)]
        self._mine_period(fast)
        bits_after_1 = self.chain.blocks[self.chain.tip].header.bits
        base_ts = fast[-1]
        fast2 = [base_ts + i * 0.01 for i in range(1, RETARGET_INTERVAL + 1)]
        self._mine_period(fast2)
        bits_after_2 = self.chain.blocks[self.chain.tip].header.bits
        self.assertGreater(bits_after_1, RETARGET_BITS)
        self.assertGreaterEqual(bits_after_2, bits_after_1)


if __name__ == "__main__":
    unittest.main()
