import copy
import unittest

from nonce.wallet import Wallet
from nonce.core.blockchain import Blockchain, create_genesis
from nonce.core.transaction import Transaction, TxIn, TxOut
from nonce.network.bus import Bus
from nonce.network.node import Node


def _make_network(names_wallets, seed=1):
    genesis = create_genesis(names_wallets[0][1].address)
    bus = Bus(seed=seed)
    nodes = {name: Node(name, Blockchain(copy.deepcopy(genesis)), bus, wallet=wallet)
             for name, wallet in names_wallets}
    return bus, nodes


class TestBus(unittest.TestCase):
    def test_drop_rate_actually_drops(self):
        bus = Bus(drop_rate=1.0, seed=1)
        received = []

        class Fake:
            id = "X"

            def handle_message(self, sender, msg_type, payload):
                received.append(payload)

        bus.register(Fake())
        bus.nodes["Y"] = type("N", (), {"handle_message": lambda self, *a: received.append("Y")})()
        bus.broadcast("X", "tx", {"data": 1})
        self.assertEqual(received, [])

    def test_partition_blocks_cross_group_delivery(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)])
        bus.partition([{"A"}, {"B", "C"}])
        block = nodes["A"].mine_block()
        self.assertNotIn(block.hash(), nodes["B"].chain.blocks)
        self.assertNotIn(block.hash(), nodes["C"].chain.blocks)

    def test_delay_ticks_requires_pump(self):
        bus = Bus(delay_ticks=3, seed=1)
        delivered = []

        class Fake:
            def __init__(self, id_):
                self.id = id_

            def handle_message(self, sender, msg_type, payload):
                delivered.append(payload)

        a, b = Fake("A"), Fake("B")
        bus.register(a)
        bus.register(b)
        bus.broadcast("A", "tx", "hello")
        self.assertEqual(delivered, [])  # not delivered yet
        bus.pump(2)
        self.assertEqual(delivered, [])  # still not enough ticks
        bus.pump(1)
        self.assertEqual(delivered, ["hello"])


class TestGossip(unittest.TestCase):
    def test_mining_propagates_to_all_nodes(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)])
        nodes["A"].mine_block()
        tips = {n.chain.tip_hash for n in nodes.values()}
        self.assertEqual(len(tips), 1)

    def test_tx_gossip_reaches_every_mempool(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)])
        nodes["A"].mine_block()
        tx = alice.build_transaction(nodes["A"].chain, bob.address, 5_00000000, fee=1000)
        nodes["A"].submit_transaction(tx)
        self.assertIn(tx.txid(), nodes["B"].mempool)
        self.assertIn(tx.txid(), nodes["C"].mempool)

    def test_invalid_tx_never_enters_any_mempool(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)])
        bad_tx = Transaction([TxIn(b"\x00" * 32, 0)], [TxOut(1, bob.address)])
        bad_tx.sign_input(0, alice.privkey)
        nodes["A"].submit_transaction(bad_tx)
        self.assertNotIn(bad_tx.txid(), nodes["A"].mempool)
        self.assertNotIn(bad_tx.txid(), nodes["B"].mempool)

    def test_confirmed_tx_leaves_all_mempools(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)])
        nodes["A"].mine_block()
        tx = alice.build_transaction(nodes["A"].chain, bob.address, 5_00000000, fee=1000)
        nodes["A"].submit_transaction(tx)
        nodes["B"].mine_block()
        for n in nodes.values():
            self.assertNotIn(tx.txid(), n.mempool)


class TestPartitionReorg(unittest.TestCase):
    def test_partition_then_heal_reconverges(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)], seed=5)
        nodes["A"].mine_block()

        bus.partition([{"A"}, {"B", "C"}])
        nodes["A"].mine_block()
        nodes["B"].mine_block()
        nodes["B"].mine_block()
        self.assertNotEqual(nodes["A"].chain.tip_hash, nodes["B"].chain.tip_hash)

        bus.heal()
        bus.resync_all()
        tips = {n.chain.tip_hash for n in nodes.values()}
        self.assertEqual(len(tips), 1)

    def test_mempool_restored_after_losing_a_fork(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)], seed=6)
        nodes["A"].mine_block()
        nodes["A"].mine_block()

        bus.partition([{"A"}, {"B", "C"}])
        utxo_key = next(iter(nodes["A"].chain.utxos_for(alice.address).items()))[0]
        only_on_a = Transaction([TxIn(*utxo_key)], [TxOut(1_00000000, carol.address)])
        only_on_a.sign_input(0, alice.privkey)
        nodes["A"].submit_transaction(only_on_a)
        nodes["A"].mine_block()  # confirms only_on_a on A's (soon-to-be-losing) fork

        nodes["B"].mine_block()
        nodes["B"].mine_block()  # B/C's fork ends up heavier

        bus.heal()
        bus.resync_all()
        self.assertEqual(nodes["A"].chain.tip_hash, nodes["B"].chain.tip_hash)
        self.assertIn(only_on_a.txid(), nodes["A"].mempool,
                       "a tx confirmed only on the losing fork must be restored to the mempool")

    def test_tx_confirmed_on_both_forks_not_double_restored(self):
        alice, bob, carol = Wallet(), Wallet(), Wallet()
        bus, nodes = _make_network([("A", alice), ("B", bob), ("C", carol)], seed=7)
        nodes["A"].mine_block()
        nodes["A"].mine_block()

        utxo_key = next(iter(nodes["A"].chain.utxos_for(alice.address).items()))[0]
        shared_tx = Transaction([TxIn(*utxo_key)], [TxOut(1_00000000, carol.address)])
        shared_tx.sign_input(0, alice.privkey)

        bus.partition([{"A"}, {"B", "C"}])
        block_a = nodes["A"].chain.mine_new_block([shared_tx], alice.address, extra_nonce=1)
        nodes["A"]._process_block(block_a, from_peer=None)
        block_b1 = nodes["B"].chain.mine_new_block([shared_tx], bob.address, extra_nonce=2)
        nodes["B"]._process_block(block_b1, from_peer=None)
        block_b2 = nodes["B"].chain.mine_new_block([], bob.address, extra_nonce=3)
        nodes["B"]._process_block(block_b2, from_peer=None)  # heavier fork

        bus.heal()
        bus.resync_all()
        self.assertEqual(nodes["A"].chain.tip_hash, nodes["B"].chain.tip_hash)
        self.assertNotIn(shared_tx.txid(), nodes["A"].mempool,
                          "a tx already confirmed on the WINNING fork must not be restored")


if __name__ == "__main__":
    unittest.main()
