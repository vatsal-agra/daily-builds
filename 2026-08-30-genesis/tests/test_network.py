import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import blockchain as bc
from helpers import make_genesis
from network import SimNetwork
from node import Node
from wallet import Wallet


def build_network(seed, n_nodes=3, latency=(0.01, 0.3)):
    genesis = make_genesis(timestamp=1_700_000_000)
    net = SimNetwork(seed=seed, latency_range=latency)
    names = [f"node{i}" for i in range(n_nodes)]
    nodes = {name: Node(name, bc.Blockchain(genesis), net, Wallet()) for name in names}
    return net, nodes, names


def run_rounds(net, nodes, names, rounds, nonce_budget, rng, start_ts=1_700_000_000):
    t = start_ts
    for _ in range(rounds):
        t += 1
        order = list(names)
        rng.shuffle(order)
        for n in order:
            nodes[n].attempt_mine(nonce_budget, t)
        net.advance_to(t)
    return t


class TestWireSerialization(unittest.TestCase):
    """Regression coverage for a Phase 3 finding: nodes used to pass live
    Python objects to each other through SimNetwork, which meant the block/
    transaction (de)serialization code was never actually exercised by the
    "network" -- a receiving node got the literal same object the sender
    built, not an independently-decoded copy. Blocks/transactions now cross
    the network as real serialized bytes."""

    def test_mined_block_reaches_peer_as_independent_object(self):
        net, nodes, names = build_network(seed=2, n_nodes=2)
        a, b = names
        block = nodes[a].attempt_mine(200_000, 1_700_000_001)
        self.assertIsNotNone(block)
        net.drain()
        self.assertEqual(nodes[b].chain.height(), 1)
        peer_block = nodes[b].chain.tip_block()
        self.assertEqual(peer_block.block_hash(), block.block_hash())
        self.assertIsNot(peer_block, block)  # genuinely a different object, not a shared reference


class TestMultiNodeConsensus(unittest.TestCase):
    def test_independent_nodes_start_identical(self):
        net, nodes, names = build_network(seed=1)
        tips = {n: nodes[n].chain.tip for n in names}
        self.assertEqual(len(set(tips.values())), 1)

    def test_network_converges_to_a_single_chain(self):
        net, nodes, names = build_network(seed=5, n_nodes=3)
        rng = random.Random(99)
        t = run_rounds(net, nodes, names, rounds=100, nonce_budget=300, rng=rng)
        net.drain()

        # a live tie in cumulative work can legitimately persist for a while;
        # keep mining (this models "given more time, ties resolve") up to a
        # bounded cap so the test is reliable without hiding a real bug.
        extra = 0
        while len({nodes[n].chain.tip for n in names}) != 1 and extra < 400:
            t += 1
            order = list(names)
            rng.shuffle(order)
            for n in order:
                nodes[n].attempt_mine(300, t)
            net.advance_to(t)
            extra += 1
        net.drain()

        tips = {n: nodes[n].chain.tip for n in names}
        self.assertEqual(len(set(tips.values())), 1, f"failed to converge: {tips}")

        # every node's UTXO set must be byte-identical once converged
        snapshots = set()
        for n in names:
            u = nodes[n].chain.utxo_set()
            key = tuple(sorted((k, v.amount, v.pubkey_hash) for k, v in u.items()))
            snapshots.add(key)
        self.assertEqual(len(snapshots), 1, "converged nodes disagree on UTXO state")

        total_mined = sum(nodes[n].stats.blocks_mined for n in names)
        self.assertGreater(total_mined, nodes[names[0]].chain.height(),
                            "test should have produced at least one real fork/orphan along the way")
        total_reorgs = sum(nodes[n].stats.reorgs_seen for n in names)
        self.assertGreaterEqual(total_reorgs, 0)  # sanity: attribute exists and is non-negative

    def test_partition_then_heal_causes_reorg_on_reconnect(self):
        net, nodes, names = build_network(seed=11, n_nodes=2, latency=(0.01, 0.05))
        a, b = names
        net.set_partitions([{a}, {b}])  # fully split: no messages cross

        rng = random.Random(3)
        t = run_rounds(net, nodes, names, rounds=1, nonce_budget=1, rng=rng)  # warm up, likely no blocks yet
        # Force node A ahead by giving it a big nonce budget alone while partitioned
        for i in range(3):
            t += 1
            block = nodes[a].attempt_mine(200_000, t)
        net.advance_to(t)
        self.assertGreaterEqual(nodes[a].chain.height(), 1)
        self.assertEqual(nodes[b].chain.height(), 0, "partitioned node B must not see A's blocks")

        # give B a couple of blocks too while still partitioned (a shorter fork)
        for i in range(1):
            t += 1
            nodes[b].attempt_mine(200_000, t)
        net.advance_to(t)
        self.assertGreater(nodes[a].chain.height(), nodes[b].chain.height())

        # heal the partition: both sides resync (a simplified stand-in for
        # request-based initial block download, see Node.announce_chain)
        net.set_partitions([])
        nodes[a].announce_chain()
        nodes[b].announce_chain()
        t += 1
        net.advance_to(t)
        net.drain()

        self.assertEqual(nodes[a].chain.tip, nodes[b].chain.tip,
                          "after healing, B must have adopted A's longer (more-work) chain")


if __name__ == "__main__":
    unittest.main()
