import copy
import time
import unittest

from bedrock.block import Block
from bedrock.chain import Chain, ChainError, COIN, block_subsidy, create_genesis_block
from bedrock.node import Node
from bedrock.transaction import Transaction, TxInput, TxOutput
from bedrock.wallet import Wallet


class TestGenesis(unittest.TestCase):
    def test_genesis_is_deterministic(self):
        # Regression for REVIEW.md #2: create_genesis_block() used to mix in
        # a random per-call nonce via Transaction.new_coinbase(), so two
        # independently started processes could never agree on genesis.
        g1 = create_genesis_block()
        g2 = create_genesis_block()
        self.assertEqual(g1.hash, g2.hash)
        self.assertEqual(g1.to_bytes(), g2.to_bytes())

    def test_two_independent_nodes_share_genesis(self):
        self.assertEqual(Node().chain.tip_hash, Node().chain.tip_hash)

    def test_genesis_satisfies_its_own_pow(self):
        from bedrock import pow as bpow
        g = create_genesis_block()
        self.assertTrue(bpow.meets_target(g.hash, g.header.target))


class TestBasicChain(unittest.TestCase):
    def setUp(self):
        self.node = Node()
        self.miner = Wallet.generate()

    def test_chain_starts_at_height_zero(self):
        self.assertEqual(self.node.chain.height, 0)

    def test_mine_extends_chain(self):
        block, status = self.node.mine_block(self.miner.address)
        self.assertEqual(status, "best_chain")
        self.assertEqual(self.node.chain.height, 1)
        self.assertEqual(self.node.balance(self.miner.address), block_subsidy(1))

    def test_mine_invalid_address_rejected(self):
        with self.assertRaises(ChainError):
            self.node.mine_block("not-a-valid-address")

    def test_duplicate_block_is_idempotent(self):
        block, _ = self.node.mine_block(self.miner.address)
        status = self.node.chain.add_block(block)
        self.assertEqual(status, "duplicate")
        self.assertEqual(self.node.chain.height, 1)

    def test_halving_schedule(self):
        from bedrock.chain import HALVING_INTERVAL, INITIAL_SUBSIDY
        self.assertEqual(block_subsidy(0), INITIAL_SUBSIDY)
        self.assertEqual(block_subsidy(HALVING_INTERVAL - 1), INITIAL_SUBSIDY)
        self.assertEqual(block_subsidy(HALVING_INTERVAL), INITIAL_SUBSIDY // 2)
        self.assertEqual(block_subsidy(HALVING_INTERVAL * 2), INITIAL_SUBSIDY // 4)


class TestBlockRejection(unittest.TestCase):
    def setUp(self):
        self.node = Node()
        self.miner = Wallet.generate()

    def _mined_copy(self):
        block, _ = self.node.mine_block(self.miner.address)
        return Block.from_bytes(block.to_bytes())[0]

    def test_tampered_coinbase_value_rejected(self):
        fresh = Node(genesis_block=self.node.chain.get_block(self.node.chain.height_index[0]))
        tampered = self._mined_copy()
        tampered.transactions[0].outputs[0].value += 1
        with self.assertRaises(ChainError):
            fresh.chain.add_block(tampered)

    def test_tampered_prev_hash_rejected(self):
        fresh = Node(genesis_block=self.node.chain.get_block(self.node.chain.height_index[0]))
        tampered = self._mined_copy()
        tampered.header.prev_hash = "ab" * 32
        # unknown parent -> orphaned, not rejected outright
        status = fresh.chain.add_block(tampered)
        self.assertEqual(status, "orphan")

    def test_invalid_pow_rejected(self):
        fresh = Node(genesis_block=self.node.chain.get_block(self.node.chain.height_index[0]))
        block, _ = self.node.mine_block(self.miner.address)
        bad = Block.from_bytes(block.to_bytes())[0]
        # Flip nonce until it no longer satisfies the target (virtually
        # certain in one try given how narrow the valid nonce set is).
        bad.header.nonce ^= 1
        from bedrock import pow as bpow
        assume_still_invalid = not bpow.meets_target(bad.hash, bad.header.target)
        self.assertTrue(assume_still_invalid, "flipped nonce coincidentally still valid; flakey test setup")
        with self.assertRaises(ChainError):
            fresh.chain.add_block(bad)

    def test_missing_coinbase_rejected(self):
        fresh = Node(genesis_block=self.node.chain.get_block(self.node.chain.height_index[0]))
        block, _ = self.node.mine_block(self.miner.address)
        bad = Block.from_bytes(block.to_bytes())[0]
        bad.transactions = bad.transactions[1:]  # drop the coinbase entirely
        bad.header.merkle_root = bad.compute_merkle_root()
        with self.assertRaises(ChainError):
            fresh.chain.add_block(bad)

    def test_second_coinbase_rejected(self):
        fresh_genesis = self.node.chain.get_block(self.node.chain.height_index[0])
        fresh = Node(genesis_block=fresh_genesis)
        block, _ = self.node.mine_block(self.miner.address)
        bad = Block.from_bytes(block.to_bytes())[0]
        bad.transactions.append(copy.deepcopy(bad.transactions[0]))
        bad.header.merkle_root = bad.compute_merkle_root()
        with self.assertRaises(ChainError):
            fresh.chain.add_block(bad)

    def test_future_timestamp_rejected(self):
        from bedrock import pow as bpow
        from bedrock.chain import MAX_FUTURE_DRIFT
        from bedrock.block import BlockHeader
        from bedrock.merkle import merkle_root as mroot
        tip = self.node.chain.tip
        coinbase = Transaction(version=1, inputs=[], outputs=[TxOutput(block_subsidy(1), self.miner.address)], coinbase_data=b"future")
        header = BlockHeader(
            version=1, prev_hash=tip.hash,
            merkle_root=mroot([bytes.fromhex(coinbase.txid)]).hex(),
            timestamp=int(time.time()) + MAX_FUTURE_DRIFT + 3600,
            target=self.node.chain.next_target(), nonce=0,
        )
        block = Block(header, [coinbase])
        bpow.mine(header, max_nonce=2_000_000)
        with self.assertRaises(ChainError):
            self.node.chain.add_block(block)


class TestDoubleSpendAndReorg(unittest.TestCase):
    def setUp(self):
        self.genesis = Node().chain.tip
        self.alice = Wallet.generate()
        self.bob = Wallet.generate()
        self.carol = Wallet.generate()

    def test_mempool_rejects_double_spend_of_pending_utxo(self):
        node = Node(genesis_block=self.genesis)
        node.mine_block(self.alice.address)
        utxo_key = node.chain.utxo_set.utxos_for_address(self.alice.address)[0][0]
        tx1 = self.alice.build_transaction(node.chain, self.bob.address, 5 * COIN, fee=100)
        self.assertTrue(node.submit_transaction(tx1))

        conflicting = Transaction(
            version=1,
            inputs=[TxInput(prev_txid=utxo_key[0], prev_index=utxo_key[1])],
            outputs=[TxOutput(5 * COIN, self.carol.address)],
        )
        conflicting.sign_input(0, self.alice.private_key, self.alice.public_key)
        with self.assertRaises(Exception):
            node.submit_transaction(conflicting)

    def test_reorg_to_heavier_fork_updates_balances(self):
        base = Node(genesis_block=self.genesis)
        base.mine_block(self.alice.address)

        node_a = Node(genesis_block=self.genesis)
        node_b = Node(genesis_block=self.genesis)
        for h in range(1, base.chain.height + 1):
            node_a.chain.add_block(base.chain.block_at_height(h))
            node_b.chain.add_block(base.chain.block_at_height(h))

        for _ in range(2):
            node_a.mine_block(self.alice.address)
        node_b.mine_block(self.bob.address)

        for h in range(base.chain.height + 1, node_a.chain.height + 1):
            node_b.chain.add_block(node_a.chain.block_at_height(h))

        self.assertEqual(node_b.chain.tip_hash, node_a.chain.tip_hash)
        self.assertEqual(node_b.balance(self.alice.address), node_a.balance(self.alice.address))

    def test_double_spend_across_forks_resolves_cleanly_on_reorg(self):
        base = Node(genesis_block=self.genesis)
        base.mine_block(self.alice.address)

        node_a = Node(genesis_block=self.genesis)
        node_b = Node(genesis_block=self.genesis)
        for h in range(1, base.chain.height + 1):
            node_a.chain.add_block(base.chain.block_at_height(h))
            node_b.chain.add_block(base.chain.block_at_height(h))

        self.alice.send(node_a.chain, node_a.mempool, self.bob.address, 10 * COIN, fee=100)
        node_a.mine_block(self.alice.address)

        self.alice.send(node_b.chain, node_b.mempool, self.carol.address, 10 * COIN, fee=100)
        node_b.mine_block(self.alice.address)
        node_b.mine_block(self.alice.address)  # heavier fork

        for h in range(base.chain.height + 1, node_b.chain.height + 1):
            node_a.chain.add_block(node_b.chain.block_at_height(h))

        self.assertEqual(node_a.chain.tip_hash, node_b.chain.tip_hash)
        self.assertEqual(node_a.balance(self.bob.address), 0)
        self.assertEqual(node_a.balance(self.carol.address), 10 * COIN)
        self.assertEqual(len(node_a.mempool), 0)


class TestMultiTxBlocksAndFees(unittest.TestCase):
    def test_coinbase_reward_includes_all_fees(self):
        node = Node()
        miner = Wallet.generate()
        for _ in range(3):
            node.mine_block(miner.address)
        fees = [500, 1000, 1500]
        for i, fee in enumerate(fees):
            miner.send(node.chain, node.mempool, Wallet.generate().address, 1 * COIN, fee=fee)
        block, status = node.mine_block(miner.address)
        self.assertEqual(status, "best_chain")
        self.assertEqual(len(block.transactions), 1 + len(fees))
        expected = block_subsidy(node.chain.height) + sum(fees)
        self.assertEqual(block.transactions[0].total_output_value(), expected)

    def test_mempool_orders_by_fee_descending(self):
        node = Node()
        miner = Wallet.generate()
        for _ in range(3):
            node.mine_block(miner.address)
        miner.send(node.chain, node.mempool, Wallet.generate().address, 1 * COIN, fee=100)
        miner.send(node.chain, node.mempool, Wallet.generate().address, 1 * COIN, fee=9000)
        miner.send(node.chain, node.mempool, Wallet.generate().address, 1 * COIN, fee=500)
        ordered = node.mempool.select_for_block(node.chain)
        fees = [node.chain.transaction_fee(tx) for tx in ordered]
        self.assertEqual(fees, sorted(fees, reverse=True))


if __name__ == "__main__":
    unittest.main()
