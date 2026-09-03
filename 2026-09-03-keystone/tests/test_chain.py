import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone import pow as pow_module
from keystone import miner
from keystone.block import Block, BlockHeader
from keystone.chain import Blockchain, ChainError, create_genesis_chain, MAX_ORPHANS
from keystone.mempool import Mempool
from keystone.transaction import make_coinbase
from keystone.wallet import Wallet

EASY_BITS = pow_module.target_to_bits(pow_module.MAX_TARGET)  # near-instant mining for fast tests


def mine_next(chain, wallet, parent_hash=None, extra_nonce=0, tamper_bits=None, height=None):
    parent_hash = parent_hash or chain.tip_hash
    # `height`/`bits` normally come from the chain's own index of
    # parent_hash -- but a test building an orphan deliberately mines a
    # block whose parent isn't in the chain yet, so both must be
    # overridable rather than looked up.
    if height is None:
        height = chain.heights[parent_hash] + 1
    bits = tamper_bits if tamper_bits is not None else chain.compute_next_bits(parent_hash)
    coinbase = make_coinbase(wallet.lock_script_for_self(), chain.block_reward_at(height), height, extra_nonce)
    header = BlockHeader(version=1, prev_hash=parent_hash, merkle_root="", timestamp=time.time() + extra_nonce * 1e-4,
                          bits=bits, nonce=0)
    blk = Block(header=header, transactions=[coinbase], height=height)
    blk.header.merkle_root = blk.compute_merkle_root()

    def prefix_fn(nonce):
        blk.header.nonce = nonce
        return blk.header.bytes_for_hash()

    result = pow_module.mine(prefix_fn, bits, max_nonce=10_000_000)
    assert result is not None, "test mining failed -- target too hard for test bits"
    nonce, _h = result
    blk.header.nonce = nonce
    return blk


class TestGenesis(unittest.TestCase):
    def test_genesis_chain_created(self):
        chain = create_genesis_chain(Wallet.generate(), bits=EASY_BITS)
        self.assertEqual(chain.height(), 0)

    def test_genesis_rejects_difficulty_easier_than_max_target(self):
        """Regression test for REVIEW.md finding #1 (the retarget cliff):
        a genesis difficulty easier than MAX_TARGET must be rejected loudly
        at construction, not left to silently cliff at the first retarget."""
        from keystone.block import make_genesis_block
        wallet = Wallet.generate()
        too_easy_bits = pow_module.target_to_bits(pow_module.MAX_TARGET * 2)
        coinbase = make_coinbase(wallet.lock_script_for_self(), 5000, 0, 0)
        genesis = make_genesis_block(coinbase, too_easy_bits, timestamp=time.time())

        def prefix_fn(nonce):
            genesis.header.nonce = nonce
            return genesis.header.bytes_for_hash()

        nonce, _h = pow_module.mine(prefix_fn, too_easy_bits, max_nonce=1000)
        genesis.header.nonce = nonce
        with self.assertRaises(ChainError):
            Blockchain(genesis)


class TestAddBlock(unittest.TestCase):
    def setUp(self):
        self.miner_wallet = Wallet.generate()
        self.chain = create_genesis_chain(self.miner_wallet, bits=EASY_BITS)
        self.mempool = Mempool()

    def test_extend_tip(self):
        blk = mine_next(self.chain, self.miner_wallet)
        result = self.chain.add_block(blk, self.mempool)
        self.assertTrue(result["accepted"])
        self.assertEqual(self.chain.height(), 1)

    def test_reject_bad_pow(self):
        blk = mine_next(self.chain, self.miner_wallet)
        blk.header.nonce += 1  # very likely breaks the PoW condition
        # re-check: only assert if it actually broke it (astronomically likely)
        if pow_module.meets_target(bytes.fromhex(blk.hash()), blk.header.bits):
            self.skipTest("nonce+1 coincidentally still valid (extremely unlikely)")
        result = self.chain.add_block(blk, self.mempool)
        self.assertFalse(result["accepted"])
        self.assertIn("target", result["reason"])

    def test_reject_bad_merkle_root(self):
        blk = mine_next(self.chain, self.miner_wallet)
        # tamper the TRANSACTIONS (not header.merkle_root directly) so the
        # already-mined header bytes -- and thus the PoW -- stay valid;
        # only compute_merkle_root() now disagrees with the stored root,
        # which is what should actually be under test here.
        extra_tx = make_coinbase(self.miner_wallet.lock_script_for_self(), 1, 999, 999)
        blk.transactions.append(extra_tx)
        result = self.chain.add_block(blk, self.mempool)
        self.assertFalse(result["accepted"])
        self.assertIn("merkle", result["reason"])

    def test_reject_wrong_difficulty_bits(self):
        blk = mine_next(self.chain, self.miner_wallet, tamper_bits=pow_module.target_to_bits(pow_module.MAX_TARGET // 2))
        result = self.chain.add_block(blk, self.mempool)
        self.assertFalse(result["accepted"])
        self.assertIn("difficulty", result["reason"])

    def test_reject_non_advancing_timestamp(self):
        blk = mine_next(self.chain, self.miner_wallet)
        blk.header.timestamp = self.chain.tip().header.timestamp  # not strictly greater
        blk.header.merkle_root = blk.compute_merkle_root()

        def prefix_fn(nonce):
            blk.header.nonce = nonce
            return blk.header.bytes_for_hash()

        nonce, _h = pow_module.mine(prefix_fn, blk.header.bits, max_nonce=100000)
        blk.header.nonce = nonce
        result = self.chain.add_block(blk, self.mempool)
        self.assertFalse(result["accepted"])
        self.assertIn("timestamp", result["reason"])

    def test_orphan_buffered_then_resolved_on_parent_arrival(self):
        blk1 = mine_next(self.chain, self.miner_wallet)
        # blk1 isn't added to self.chain yet, so its height/bits can't be
        # looked up from the chain's own index -- pass them explicitly.
        blk2 = mine_next(self.chain, self.miner_wallet, parent_hash=blk1.hash(), extra_nonce=1,
                          height=2, tamper_bits=EASY_BITS)
        result = self.chain.add_block(blk2, self.mempool)  # parent (blk1) not yet known
        self.assertTrue(result["orphan"])
        self.assertEqual(self.chain.height(), 0)

        result = self.chain.add_block(blk1, self.mempool)
        self.assertTrue(result["accepted"])
        self.assertEqual(self.chain.height(), 2)
        self.assertEqual(self.chain.tip_hash, blk2.hash())

    def test_idempotent_readd(self):
        blk = mine_next(self.chain, self.miner_wallet)
        r1 = self.chain.add_block(blk, self.mempool)
        r2 = self.chain.add_block(blk, self.mempool)
        self.assertTrue(r1["accepted"] and r2["accepted"])
        self.assertEqual(self.chain.height(), 1)


class TestReorg(unittest.TestCase):
    def setUp(self):
        self.miner_wallet = Wallet.generate()
        self.chain = create_genesis_chain(self.miner_wallet, bits=EASY_BITS)
        self.mempool = Mempool()

    def test_more_work_triggers_reorg(self):
        alice, bob = Wallet.generate(), Wallet.generate()
        branch_point = self.chain.tip_hash

        a1 = mine_next(self.chain, alice, parent_hash=branch_point, extra_nonce=1)
        self.chain.add_block(a1, self.mempool)  # alice's block becomes tip (only branch so far)

        # bob mines a competing block on the SAME parent (a sibling of a1)
        b1 = mine_next(self.chain, bob, parent_hash=branch_point, extra_nonce=2)
        self.chain.add_block(b1, self.mempool)
        self.assertEqual(self.chain.tip_hash, a1.hash())  # first-seen wins a tie

        # bob extends his branch -> now has strictly more work -> must reorg
        b2 = mine_next(self.chain, bob, parent_hash=b1.hash(), extra_nonce=3)
        result = self.chain.add_block(b2, self.mempool)
        self.assertTrue(result["reorged"])
        self.assertEqual(self.chain.tip_hash, b2.hash())
        self.assertEqual(self.chain.total_reorgs, 1)
        # alice's coinbase reward must no longer be reflected in the active UTXO set
        self.assertEqual(self.chain.utxo_set.balance_of(alice.pubkey_hash), 0)
        self.assertGreater(self.chain.utxo_set.balance_of(bob.pubkey_hash), 0)

    def test_reorg_reported_even_through_orphan_resolution(self):
        """Regression test for REVIEW.md finding #2: a reorg triggered by
        the recursive orphan-resolution path (not the directly-added block)
        must still be counted."""
        alice, bob = Wallet.generate(), Wallet.generate()
        branch_point = self.chain.tip_hash

        a1 = mine_next(self.chain, alice, parent_hash=branch_point, extra_nonce=1)
        self.chain.add_block(a1, self.mempool)

        b1 = mine_next(self.chain, bob, parent_hash=branch_point, extra_nonce=2)
        b2 = mine_next(self.chain, bob, parent_hash=b1.hash(), extra_nonce=3, height=2, tamper_bits=EASY_BITS)
        # feed b2 BEFORE b1 -- b2 becomes an orphan, and the eventual reorg
        # (once b1 arrives and unblocks it) happens via the orphan queue,
        # not the direct add_block(b2, ...) call
        self.chain.add_block(b2, self.mempool)
        result = self.chain.add_block(b1, self.mempool)
        self.assertEqual(self.chain.tip_hash, b2.hash())
        self.assertEqual(self.chain.total_reorgs, 1, "reorg via orphan resolution must still be counted")


class TestOrphanRecursionSafety(unittest.TestCase):
    def test_deep_reverse_fed_chain_does_not_recurse(self):
        """Regression test for REVIEW.md finding #5: a long chain of
        buffered orphans, fed in reverse order (worst case for the old
        recursive implementation), must resolve without hitting Python's
        recursion limit -- verified by aggressively lowering the limit so
        even a moderate depth would have crashed the old code."""
        wallet = Wallet.generate()
        seed_chain = create_genesis_chain(wallet, bits=EASY_BITS)
        genesis = seed_chain.blocks[seed_chain.tip_hash]

        builder = Blockchain(genesis)
        depth = 80  # comfortably under MAX_ORPHANS, well beyond a lowered recursion limit
        blocks = []
        mp = Mempool()
        for i in range(depth):
            blk = mine_next(builder, wallet, extra_nonce=i)
            res = builder.add_block(blk, mp)
            self.assertTrue(res["accepted"])
            blocks.append(blk)

        chain = Blockchain(genesis)
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(50)
        try:
            for blk in reversed(blocks):
                chain.add_block(blk)
        finally:
            sys.setrecursionlimit(old_limit)

        self.assertEqual(chain.height(), depth)
        self.assertEqual(chain.tip_hash, blocks[-1].hash())

    def test_orphan_pool_capped(self):
        wallet = Wallet.generate()
        seed_chain = create_genesis_chain(wallet, bits=EASY_BITS)
        genesis = seed_chain.blocks[seed_chain.tip_hash]
        chain = Blockchain(genesis)

        # feed MAX_ORPHANS + 20 blocks that all reference unknown parents
        # (never actually resolvable) -- the pool must never grow past the cap
        import hashlib
        for i in range(MAX_ORPHANS + 20):
            fake_parent = hashlib.sha256(f"never-exists-{i}".encode()).hexdigest()
            coinbase = make_coinbase(wallet.lock_script_for_self(), 5000, 1, i)
            header = BlockHeader(version=1, prev_hash=fake_parent, merkle_root="", timestamp=time.time(),
                                  bits=EASY_BITS, nonce=0)
            blk = Block(header=header, transactions=[coinbase], height=1)
            blk.header.merkle_root = blk.compute_merkle_root()

            def prefix_fn(nonce, blk=blk):
                blk.header.nonce = nonce
                return blk.header.bytes_for_hash()

            nonce, _h = pow_module.mine(prefix_fn, EASY_BITS, max_nonce=1000)
            blk.header.nonce = nonce

            chain.add_block(blk)
            self.assertLessEqual(len(chain.orphans), MAX_ORPHANS)


if __name__ == "__main__":
    unittest.main()
