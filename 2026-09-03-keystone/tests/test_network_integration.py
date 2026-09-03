"""Integration tests over real TCP sockets and real threads -- these are
slower than the unit tests but exercise the actual thing the CLI demo
exercises: independent nodes gossiping and converging."""
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone import pow as pow_module
from keystone import wire
from keystone.chain import Blockchain, create_genesis_chain
from keystone.node import FullNode
from keystone.wallet import Wallet

EASY_BITS = pow_module.target_to_bits(pow_module.MAX_TARGET)
_next_port = [23100]


def alloc_port_range(n):
    base = _next_port[0]
    _next_port[0] += n + 5
    return base


def make_network(n, base_port, wallets=None):
    genesis_wallet = Wallet.generate()
    seed = create_genesis_chain(genesis_wallet, bits=EASY_BITS)
    genesis = seed.blocks[seed.tip_hash]
    wallets = wallets or [Wallet.generate() for _ in range(n)]
    nodes = []
    for i in range(n):
        chain = Blockchain(genesis)
        node = FullNode("127.0.0.1", base_port + i, chain, miner_wallet=wallets[i], name=f"n{i}")
        node.start()
        nodes.append(node)
    return nodes, wallets


def wait_until(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class TestGossipConvergence(unittest.TestCase):
    def test_ring_network_converges_and_balances_match(self):
        n = 4
        base_port = alloc_port_range(n)
        nodes, wallets = make_network(n, base_port)
        try:
            for i in range(n):
                nodes[i].connect_to("127.0.0.1", base_port + ((i + 1) % n))
            time.sleep(0.3)
            for node in nodes:
                node.start_mining()

            ok = wait_until(lambda: min(n.chain.height() for n in nodes) >= 6, timeout=15)
            self.assertTrue(ok, "network failed to mine 6 blocks in time")

            for node in nodes:
                node.stop_mining()
            converged = wait_until(lambda: len({n.chain.tip_hash for n in nodes}) == 1, timeout=10)
            self.assertTrue(converged)

            for wallet in wallets:
                balances = {n.chain.utxo_set.balance_of(wallet.pubkey_hash) for n in nodes}
                self.assertEqual(len(balances), 1, "all nodes must agree on every wallet's balance")
        finally:
            for node in nodes:
                node.stop()

    def test_transaction_relays_and_confirms_across_network(self):
        n = 3
        base_port = alloc_port_range(n)
        nodes, wallets = make_network(n, base_port)
        try:
            for i in range(n):
                nodes[i].connect_to("127.0.0.1", base_port + ((i + 1) % n))
            time.sleep(0.3)
            for node in nodes:
                node.start_mining()

            def find_spendable():
                for node, wallet in zip(nodes, wallets):
                    for (txid, idx), (txout, h, is_cb) in node.chain.utxo_set.utxos.items():
                        if txout.script_pubkey == wallet.lock_script_for_self() and \
                                (not is_cb or node.chain.height() - h >= 2):
                            return node, wallet, txid, idx, txout.amount
                return None

            deadline = time.time() + 15
            found = None
            while time.time() < deadline and found is None:
                found = find_spendable()
                time.sleep(0.1)
            self.assertIsNotNone(found, "no node ever got a matured spendable output")
            sender_node, sender_wallet, txid, idx, amount = found

            recipient = wallets[(nodes.index(sender_node) + 1) % n]
            before = {n: n.chain.utxo_set.balance_of(recipient.pubkey_hash) for n in nodes}
            tx = sender_wallet.build_transaction([(txid, idx)], [(amount - 1000, recipient.pubkey_hash)])
            self.assertTrue(sender_node.submit_transaction(tx))

            def landed_everywhere():
                return all(n.chain.utxo_set.balance_of(recipient.pubkey_hash) > before[n] for n in nodes)

            ok = wait_until(landed_everywhere, timeout=15)
            for node in nodes:
                node.stop_mining()
            self.assertTrue(ok, "transaction never confirmed on every node")
        finally:
            for node in nodes:
                node.stop()


class TestPartitionAndReorg(unittest.TestCase):
    def test_diverged_partition_reconverges_on_reconnect(self):
        base_port = alloc_port_range(3)
        genesis_wallet = Wallet.generate()
        seed = create_genesis_chain(genesis_wallet, bits=EASY_BITS)
        genesis = seed.blocks[seed.tip_hash]

        def make_node(i):
            chain = Blockchain(genesis)
            node = FullNode("127.0.0.1", base_port + i, chain, miner_wallet=Wallet.generate(), name=f"p{i}")
            node.start()
            return node

        a = make_node(0)
        b = make_node(1)
        try:
            for node in (a, b):
                node.start_mining()
            time.sleep(2.5)
            for node in (a, b):
                node.stop_mining()
            time.sleep(0.2)
            diverged = a.chain.tip_hash != b.chain.tip_hash or a.chain.height() != b.chain.height()

            b.connect_to("127.0.0.1", base_port + 0)
            time.sleep(0.2)
            for node in (a, b):
                node.start_mining()

            converged = wait_until(lambda: a.chain.tip_hash == b.chain.tip_hash, timeout=15)
            for node in (a, b):
                node.stop_mining()
            self.assertTrue(converged)
            if diverged:
                self.assertGreaterEqual(a.net.reorg_count + b.net.reorg_count, 1)
        finally:
            for node in (a, b):
                node.stop()


class TestMalformedMessageHandling(unittest.TestCase):
    def test_node_survives_malformed_messages(self):
        """Regression test for REVIEW.md finding #6."""
        base_port = alloc_port_range(1)
        seed = create_genesis_chain(Wallet.generate(), bits=EASY_BITS)
        genesis = seed.blocks[seed.tip_hash]
        chain = Blockchain(genesis)
        node = FullNode("127.0.0.1", base_port, chain, miner_wallet=Wallet.generate(), name="victim")
        node.start()
        try:
            time.sleep(0.2)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", base_port))
            wire.send_msg(sock, {"type": "block"})  # missing required "block" key
            wire.send_msg(sock, {"type": "tx", "tx": "not-a-real-tx-dict"})
            wire.send_msg(sock, {"type": "inv_block"})  # missing "hash"
            wire.send_msg(sock, {"type": "totally-unknown-type"})
            time.sleep(0.3)

            self.assertTrue(node.net.running)
            # the connection must still be usable afterward
            wire.send_msg(sock, {"type": "version", "height": 0, "port": 1})
            time.sleep(0.2)
            self.assertEqual(node.net.peer_count(), 1)
            sock.close()
        finally:
            node.stop()


if __name__ == "__main__":
    unittest.main()
