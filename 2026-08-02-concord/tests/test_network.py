import unittest

from concord import pow as powmod
from concord._netutil import spin_up_network, tx_is_known, wait_until
from concord.block import Block
from concord.chain import Blockchain
from concord.mempool import Mempool
from concord.miner import Miner, mine_block
from concord.node import Node
from concord.wallet import Wallet

EASY_TARGET = powmod.MAX_TARGET >> 8
FAST_TARGET = powmod.MAX_TARGET >> 12  # a bit harder than unit-test target, still fast


class TestTwoNodeGossipAndSync(unittest.TestCase):
    def test_mined_blocks_and_transactions_propagate(self):
        alice = Wallet()
        bob = Wallet()
        genesis = Block.genesis(alice.address, FAST_TARGET, amount=1000)
        net = spin_up_network(genesis, count=2, base_port=28001)
        try:
            miner = Miner(net.nodes[0], alice.address)
            miner.start()
            self.assertTrue(wait_until(lambda: net.nodes[0].chain.height() >= 2, timeout=20))
            self.assertTrue(wait_until(
                lambda: net.nodes[1].chain.tip_hash == net.nodes[0].chain.tip_hash, timeout=15
            ))

            tx = alice.build_transaction(net.nodes[0].chain.utxo, bob.address, 111)
            self.assertTrue(net.nodes[0].submit_transaction(tx))
            self.assertTrue(wait_until(lambda: tx_is_known(net.nodes[1], tx.txid()), timeout=10))

            self.assertTrue(wait_until(lambda: bob.balance(net.nodes[0].chain.utxo) == 111, timeout=20))
            miner.stop()
            self.assertTrue(wait_until(
                lambda: net.nodes[1].chain.tip_hash == net.nodes[0].chain.tip_hash, timeout=10
            ))
            self.assertEqual(bob.balance(net.nodes[1].chain.utxo), 111)
        finally:
            net.stop()

    def test_late_joining_node_catches_up_fully(self):
        alice = Wallet()
        genesis = Block.genesis(alice.address, FAST_TARGET, amount=1000)
        net = spin_up_network(genesis, count=1, base_port=28101)
        try:
            miner = Miner(net.nodes[0], alice.address)
            miner.start()
            self.assertTrue(wait_until(lambda: net.nodes[0].chain.height() >= 4, timeout=20))
            miner.stop()

            # a second node joins only now, well after several blocks exist
            late_chain = Blockchain(genesis)
            late_node = Node("127.0.0.1", 28102, late_chain, Mempool(), name="late")
            late_node.start()
            late_node.connect("127.0.0.1", net.nodes[0].port)
            self.assertTrue(wait_until(
                lambda: late_chain.tip_hash == net.nodes[0].chain.tip_hash, timeout=15
            ))
            self.assertEqual(late_chain.height(), net.nodes[0].chain.height())
            late_node.stop()
        finally:
            net.stop()

    def test_node_that_forked_away_resyncs_via_gossip_not_stuck(self):
        # this is a regression test for the exact bug found in REVIEW.md
        # finding #1: a node that falls behind by more than one block must
        # not get stuck on inv_block alone (which only ever fetches the
        # single newest block) — it must fall back to a full chain sync.
        alice = Wallet()
        genesis = Block.genesis(alice.address, FAST_TARGET, amount=1000)
        net = spin_up_network(genesis, count=2, base_port=28201)
        try:
            # let node1 fall behind: mine several blocks on node0 alone
            # while node1's connection is still up (gossip races legitimately
            # move a peer more than 1 block behind under real timing)
            miner = Miner(net.nodes[0], alice.address)
            miner.start()
            self.assertTrue(wait_until(lambda: net.nodes[0].chain.height() >= 6, timeout=25))
            miner.stop()
            self.assertTrue(wait_until(
                lambda: net.nodes[1].chain.tip_hash == net.nodes[0].chain.tip_hash, timeout=20
            ))
            self.assertEqual(net.nodes[1].chain.height(), net.nodes[0].chain.height())
        finally:
            net.stop()


class TestForkResolutionAcrossRealNodes(unittest.TestCase):
    def test_reconnecting_after_a_private_fork_adopts_more_work_chain(self):
        alice = Wallet()
        genesis = Block.genesis(alice.address, FAST_TARGET, amount=1000)
        net = spin_up_network(genesis, count=2, base_port=28301)
        try:
            miner0 = Miner(net.nodes[0], alice.address)
            miner1 = Miner(net.nodes[1], alice.address)
            miner0.start()
            miner1.start()
            self.assertTrue(wait_until(lambda: net.nodes[0].chain.height() >= 3, timeout=20))
            self.assertTrue(wait_until(
                lambda: net.nodes[1].chain.tip_hash == net.nodes[0].chain.tip_hash, timeout=15
            ))
            miner0.stop()
            miner1.stop()

            # a fresh isolated node replays the same real blocks up to height 1,
            # then privately mines its own single competing block at height 2
            replay_chain = Blockchain(genesis)
            for h in net.nodes[0].chain.main_chain_hashes()[1:2]:
                ok, _, _, reason = replay_chain.add_block(net.nodes[0].chain.get_block(h))
                self.assertTrue(ok, reason)
            from concord.block import Block as BlockCls
            from concord.transaction import Transaction
            private_cb = Transaction.new_coinbase(alice.address, 50, height=2, extra="private")
            private_block = BlockCls(2, replay_chain.tip_hash, [private_cb], replay_chain.next_block_target())
            private_block = mine_block(private_block)
            ok, became_tip, _, reason = replay_chain.add_block(private_block)
            self.assertTrue(ok and became_tip, reason)

            private_node = Node("127.0.0.1", 28303, replay_chain, Mempool(), name="private")
            private_node.start()
            private_node.connect("127.0.0.1", net.nodes[0].port)

            # node0's real chain has strictly more work (3+ blocks vs 2), so
            # the private node must adopt node0's chain, not the other way around
            self.assertTrue(wait_until(
                lambda: private_node.chain.tip_hash == net.nodes[0].chain.tip_hash, timeout=15
            ))
            private_node.stop()
        finally:
            net.stop()


if __name__ == "__main__":
    unittest.main()
