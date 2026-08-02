import unittest

from concord import pow as powmod
from concord.block import Block
from concord.chain import BASE_REWARD, Blockchain
from concord.mempool import Mempool
from concord.miner import build_candidate, mine_block
from concord.transaction import Transaction, TxInput, TxOutput
from concord.wallet import Wallet

EASY_TARGET = powmod.MAX_TARGET >> 8


def fresh_chain(amount=1000):
    alice = Wallet()
    genesis = Block.genesis(alice.address, EASY_TARGET, amount=amount)
    return Blockchain(genesis), alice


class TestMineBlock(unittest.TestCase):
    def test_mine_block_finds_a_valid_nonce(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        block = Block(1, chain.tip_hash, [cb], EASY_TARGET)
        solved = mine_block(block)
        self.assertIsNotNone(solved)
        self.assertTrue(powmod.meets_target(bytes.fromhex(solved.hash()), solved.target))

    def test_mine_block_respects_stop_check(self):
        chain, alice = fresh_chain()
        cb = Transaction.new_coinbase(alice.address, BASE_REWARD, height=1)
        # an effectively-impossible target so it never actually solves
        block = Block(1, chain.tip_hash, [cb], 1)
        result = mine_block(block, stop_check=lambda: True)
        self.assertIsNone(result)


class TestBuildCandidate(unittest.TestCase):
    def test_candidate_includes_valid_pending_transaction_and_pays_fee(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        mempool = Mempool()
        tx = alice.build_transaction(chain.utxo, bob.address, 100, fee=3)
        mempool.add_transaction(tx, chain.utxo)
        candidate = build_candidate(chain, mempool, alice.address)
        txids = {t.txid() for t in candidate.transactions}
        self.assertIn(tx.txid(), txids)
        coinbase = candidate.transactions[0]
        self.assertTrue(coinbase.is_coinbase)
        self.assertEqual(coinbase.total_output(), BASE_REWARD + 3)

    def test_candidate_never_selects_two_conflicting_transactions(self):
        chain, alice = fresh_chain()
        bob = Wallet()
        carol = Wallet()
        mempool = Mempool()
        snapshot = dict(chain.utxo)
        tx_a = alice.build_transaction(snapshot, bob.address, 100)
        tx_b = alice.build_transaction(snapshot, carol.address, 100)
        self.assertEqual(
            {(i.txid, i.index) for i in tx_a.inputs},
            {(i.txid, i.index) for i in tx_b.inputs},
            "test setup bug: these must conflict to prove anything",
        )
        # bypass Mempool's own conflict rejection to simulate two pooled
        # transactions that conflict (e.g. a race before propagation caught up)
        mempool.transactions[tx_a.txid()] = tx_a
        mempool.transactions[tx_b.txid()] = tx_b

        candidate = build_candidate(chain, mempool, alice.address)
        included_ids = {t.txid() for t in candidate.transactions if not t.is_coinbase}
        self.assertEqual(len(included_ids & {tx_a.txid(), tx_b.txid()}), 1,
                          "exactly one side of the conflict may be selected, never both, never neither")

    def test_candidate_with_empty_mempool_is_coinbase_only(self):
        chain, alice = fresh_chain()
        candidate = build_candidate(chain, Mempool(), alice.address)
        self.assertEqual(len(candidate.transactions), 1)
        self.assertTrue(candidate.transactions[0].is_coinbase)


if __name__ == "__main__":
    unittest.main()
