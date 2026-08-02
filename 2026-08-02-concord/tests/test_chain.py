import time
import unittest

from concord import curve, pow as powmod
from concord.block import Block
from concord.chain import BASE_REWARD, Blockchain
from concord.transaction import Transaction, TxInput, TxOutput
from concord.wallet import Wallet

EASY_TARGET = powmod.MAX_TARGET >> 8  # trivial to mine, keeps unit tests fast


def mine(block):
    while not powmod.meets_target(bytes.fromhex(block.hash()), block.target):
        block.nonce += 1
    return block


def find_non_meeting_nonce(block):
    """A nonce for which this block's hash does NOT meet its own target —
    for testing the target check in isolation, with a correctly-set
    block.target (so an earlier, unrelated check doesn't fire instead)."""
    while powmod.meets_target(bytes.fromhex(block.hash()), block.target):
        block.nonce += 1
    return block


def fresh_chain(amount=1000):
    alice = Wallet()
    genesis = Block.genesis(alice.address, EASY_TARGET, amount=amount)
    return Blockchain(genesis), alice


def mined_block(chain, transactions, height=None, prev_hash=None, target=None, timestamp=None):
    height = chain.height() + 1 if height is None else height
    prev_hash = chain.tip_hash if prev_hash is None else prev_hash
    target = chain.next_block_target() if target is None else target
    b = Block(height, prev_hash, transactions, target, timestamp=timestamp)
    return mine(b)


class TestGenesisAndBasicAcceptance(unittest.TestCase):
    def test_genesis_premine_applied(self):
        chain, alice = fresh_chain(amount=777)
        self.assertEqual(alice.balance(chain.utxo), 777)
        self.assertEqual(chain.height(), 0)

    def test_valid_block_extends_tip(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb])
        ok, became_tip, orphaned, reason = chain.add_block(b1)
        self.assertTrue(ok, reason)
        self.assertTrue(became_tip)
        self.assertEqual(chain.height(), 1)
        self.assertEqual(alice.balance(chain.utxo), 1000 + BASE_REWARD)

    def test_payment_transaction_moves_funds(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        tx = alice.build_transaction(chain.utxo, bob.address, 100)
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb, tx])
        ok, _, _, reason = chain.add_block(b1)
        self.assertTrue(ok, reason)
        self.assertEqual(bob.balance(chain.utxo), 100)
        self.assertEqual(alice.balance(chain.utxo), 1000 - 100 + BASE_REWARD)

    def test_duplicate_block_is_idempotent(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb])
        chain.add_block(b1)
        ok, became_tip, _, reason = chain.add_block(b1)
        self.assertTrue(ok)
        self.assertFalse(became_tip)
        self.assertEqual(reason, "already known")


class TestRejections(unittest.TestCase):
    def test_rejects_pow_that_does_not_meet_target(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        # target field is the real expected one (so the earlier "wrong
        # difficulty target" check doesn't fire instead) but the nonce is
        # deliberately one that doesn't satisfy it
        b1 = Block(1, chain.tip_hash, [cb], chain.next_block_target())
        b1 = find_non_meeting_nonce(b1)
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("proof-of-work", reason)

    def test_rejects_wrong_difficulty_target(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb], target=EASY_TARGET >> 1)
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("difficulty target", reason)

    def test_rejects_wrong_height(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb], height=5)
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("height", reason)

    def test_rejects_unknown_parent(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb], prev_hash="ab" * 32)
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("unknown parent", reason)

    def test_rejects_timestamp_before_parent(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb], timestamp=-100.0)
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("timestamp before parent", reason)

    def test_rejects_timestamp_far_in_future(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb], timestamp=time.time() + 999999)
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("future", reason)

    def test_rejects_double_spend_within_block(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        tx1 = alice.build_transaction(chain.utxo, bob.address, 100)
        # a second tx trying to spend the exact same input again, to a third party
        carol = Wallet()
        forged_input = TxInput(tx1.inputs[0].txid, tx1.inputs[0].index, pubkey=alice.pubkey_bytes)
        tx2 = Transaction([forged_input], [TxOutput(50, carol.address)])
        tx2.sign_input(0, alice.private_key)
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb, tx1, tx2])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("double-spend", reason)

    def test_rejects_spend_of_nonexistent_output(self):
        chain, alice = fresh_chain()
        bogus_input = TxInput("00" * 32, 0, pubkey=alice.pubkey_bytes)
        tx = Transaction([bogus_input], [TxOutput(10, alice.address)])
        tx.sign_input(0, alice.private_key)
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb, tx])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("unknown or already-spent", reason)

    def test_rejects_invalid_signature(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        tx = alice.build_transaction(chain.utxo, bob.address, 100)
        tx.inputs[0].signature = bytes(b ^ 0xFF for b in tx.inputs[0].signature)
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb, tx])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("signature", reason)

    def test_rejects_pubkey_not_matching_utxo_owner(self):
        chain, alice = fresh_chain()
        mallory = Wallet()
        bob = Wallet()
        # mallory tries to spend alice's UTXO by attaching her own pubkey/signature
        key = next(iter(chain.utxo))
        forged = TxInput(key[0], key[1], pubkey=mallory.pubkey_bytes)
        tx = Transaction([forged], [TxOutput(10, bob.address)])
        tx.sign_input(0, mallory.private_key)
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb, tx])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("owning address", reason)

    def test_rejects_outputs_exceeding_inputs(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        key = next(iter(chain.utxo))
        amount = chain.utxo[key].amount
        inp = TxInput(key[0], key[1], pubkey=alice.pubkey_bytes)
        tx = Transaction([inp], [TxOutput(amount + 1, bob.address)])
        tx.sign_input(0, alice.private_key)
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        b1 = mined_block(chain, [cb, tx])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("outputs exceed inputs", reason)

    def test_rejects_coinbase_overpay(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD + 1, height=1)
        b1 = mined_block(chain, [cb])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("coinbase pays", reason)

    def test_coinbase_may_include_fees(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        tx = alice.build_transaction(chain.utxo, bob.address, 100, fee=5)
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD + 5, height=1)
        b1 = mined_block(chain, [cb, tx])
        ok, _, _, reason = chain.add_block(b1)
        self.assertTrue(ok, reason)

    def test_rejects_multiple_coinbases(self):
        chain, alice = fresh_chain()
        cb1 = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1, extra="a")
        cb2 = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1, extra="b")
        b1 = mined_block(chain, [cb1, cb2])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("coinbase", reason)

    def test_rejects_missing_coinbase(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        tx = alice.build_transaction(chain.utxo, bob.address, 10)
        b1 = mined_block(chain, [tx])
        ok, _, _, reason = chain.add_block(b1)
        self.assertFalse(ok)
        self.assertIn("coinbase", reason)


class TestForkAndReorg(unittest.TestCase):
    def test_reorg_switches_to_higher_work_chain_and_restores_orphaned_tx(self):
        chain, alice = fresh_chain()
        bob = Wallet()

        # branch A: one block containing a real payment to bob
        cb_a = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1, extra="A")
        tx = alice.build_transaction(chain.utxo, bob.address, 100)
        block_a = mined_block(chain, [cb_a, tx])
        ok, became_tip, _, reason = chain.add_block(block_a)
        self.assertTrue(ok and became_tip, reason)
        self.assertEqual(bob.balance(chain.utxo), 100)

        # branch B: two competing blocks from genesis, no payment to bob,
        # each mined at a harder (lower) target so they carry more total work
        # than branch A's single block even though branch A is "longer" by height
        # equal — we make B out-work A by using two blocks at the same target
        harder_target = EASY_TARGET
        # block_b1 ties branch A's cumulative work exactly (same parent,
        # same expected_target, one block each) — the tie-break is a real
        # coin flip by hash, so its became_tip is deliberately NOT asserted
        # here; block_b2 below gives branch B strictly more work than
        # branch A regardless of how that tie landed, which is the actual
        # invariant this test cares about
        cb_b1 = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1, extra="B1")
        block_b1 = Block(1, chain.genesis_hash, [cb_b1], harder_target)
        block_b1 = mine(block_b1)
        ok, _, orphaned_1, reason = chain.add_block(block_b1)
        self.assertTrue(ok, reason)

        cb_b2 = Transaction.new_coinbase(alice.address, BASE_REWARD, height=2, extra="B2")
        block_b2 = Block(2, block_b1.hash(), [cb_b2], chain.expected_target(block_b1.hash()))
        block_b2 = mine(block_b2)
        ok, became_tip, orphaned_2, reason = chain.add_block(block_b2)
        self.assertTrue(ok, reason)
        self.assertTrue(became_tip, "branch B has strictly more cumulative work and must win")

        # branch A's payment to bob must be gone from the now-canonical chain...
        self.assertEqual(bob.balance(chain.utxo), 0)
        # ...and the orphaned real payment tx must be handed back for the mempool to
        # reconsider. WHICH call reports it depends on the block_a/block_b1 tie-break
        # (if b1 won the tie outright, orphaning happens there; if block_a held on,
        # orphaning happens when b2 finally overtakes it) — union both so the test is
        # correct either way instead of depending on that coin flip.
        orphaned_ids = {t.txid() for t in orphaned_1} | {t.txid() for t in orphaned_2}
        self.assertIn(tx.txid(), orphaned_ids)

    def test_side_branch_block_is_validated_but_not_activated(self):
        # two same-target competing height-1 blocks are a genuine tie in
        # cumulative work (identical parent -> identical expected_target),
        # and the tie-break can legitimately go either way by hash — so to
        # deterministically test "a lower-work branch is stored but never
        # activated", branch A is extended to TWO blocks (strictly more
        # work) before the single-block branch B is offered
        chain, alice = fresh_chain()
        cb_a1 = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1, extra="A1")
        block_a1 = mined_block(chain, [cb_a1])
        chain.add_block(block_a1)
        cb_a2 = Transaction.new_coinbase(alice.address, BASE_REWARD, height=2, extra="A2")
        block_a2 = mined_block(chain, [cb_a2])
        ok, became_tip, _, reason = chain.add_block(block_a2)
        self.assertTrue(ok and became_tip, reason)

        cb_b = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1, extra="B")
        block_b = Block(1, chain.genesis_hash, [cb_b], EASY_TARGET)
        block_b = mine(block_b)
        ok, became_tip, _, reason = chain.add_block(block_b)
        self.assertTrue(ok, reason)
        self.assertFalse(became_tip, "branch B (1 block of work) must not beat branch A (2 blocks of work)")
        self.assertEqual(chain.tip_hash, block_a2.hash())
        # but it's still stored and known, available if branch B is ever extended further
        self.assertTrue(chain.has_block(block_b.hash()))


class TestDifficultyRetarget(unittest.TestCase):
    def test_target_unchanged_before_retarget_interval(self):
        chain, alice = fresh_chain()
        for h in range(1, powmod.RETARGET_INTERVAL):
            cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=h, extra=str(h))
            block = mined_block(chain, [cb])
            self.assertEqual(block.target, EASY_TARGET)
            ok, _, _, reason = chain.add_block(block)
            self.assertTrue(ok, reason)

    def test_slow_blocks_make_next_target_easier(self):
        chain, alice = fresh_chain()
        t = 0.0
        for h in range(1, powmod.RETARGET_INTERVAL + 1):
            t += 1000.0  # far slower than TARGET_BLOCK_SECONDS
            cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=h, extra=str(h))
            block = mined_block(chain, [cb], timestamp=t)
            ok, _, _, reason = chain.add_block(block)
            self.assertTrue(ok, reason)
        self.assertGreater(chain.next_block_target(), EASY_TARGET)


if __name__ == "__main__":
    unittest.main()
