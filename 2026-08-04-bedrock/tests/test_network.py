import json
import socket
import time
import unittest

from bedrock.chain import COIN, block_subsidy
from bedrock.network import NetworkNode, wait_until_converged
from bedrock.node import Node
from bedrock.wallet import Wallet


class TestNetworkGossip(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for n in self.nodes:
            n.stop()

    def _spawn(self, n=3):
        nodes = [NetworkNode(Node()) for _ in range(n)]
        for nn in nodes:
            nn.start()
        self.nodes.extend(nodes)
        return nodes

    def test_independently_constructed_nodes_share_genesis(self):
        a, b = self._spawn(2)
        self.assertEqual(a.node.chain.tip_hash, b.node.chain.tip_hash)

    def test_two_nodes_converge_after_connect_and_mine(self):
        a, b = self._spawn(2)
        b.connect("127.0.0.1", a.port)
        time.sleep(0.3)
        self.assertEqual(a.peer_count(), 1)
        miner = Wallet.generate()
        block, _ = a.node.mine_block(miner.address)
        a.announce_block(block)
        self.assertTrue(wait_until_converged([a, b], timeout=8))
        self.assertEqual(b.node.balance(miner.address), block_subsidy(1))

    def test_hub_and_two_spokes_converge(self):
        hub, spoke1, spoke2 = self._spawn(3)
        spoke1.connect("127.0.0.1", hub.port)
        spoke2.connect("127.0.0.1", hub.port)
        time.sleep(0.3)
        self.assertEqual(hub.peer_count(), 2)
        block, _ = hub.node.mine_block(Wallet.generate().address)
        hub.announce_block(block)
        self.assertTrue(wait_until_converged([hub, spoke1, spoke2], timeout=8))

    def test_simultaneous_fork_resolves_after_tiebreak(self):
        a, b, c = self._spawn(3)
        b.connect("127.0.0.1", a.port)
        c.connect("127.0.0.1", a.port)
        time.sleep(0.3)
        block0, _ = a.node.mine_block(Wallet.generate().address)
        a.announce_block(block0)
        self.assertTrue(wait_until_converged([a, b, c], timeout=8))

        fork1, _ = b.node.mine_block(Wallet.generate().address)
        fork2, _ = c.node.mine_block(Wallet.generate().address)
        b.announce_block(fork1)
        c.announce_block(fork2)
        time.sleep(0.5)
        # not asserting divergence here (it's a legitimate, allowed transient
        # state) — only that a tiebreaking block resolves it
        tiebreak, _ = a.node.mine_block(Wallet.generate().address)
        a.announce_block(tiebreak)
        self.assertTrue(wait_until_converged([a, b, c], timeout=8))

    def test_late_joiner_syncs_full_chain(self):
        a, = self._spawn(1)
        for _ in range(3):
            block, _ = a.node.mine_block(Wallet.generate().address)
            a.announce_block(block)
        late, = self._spawn(1)
        self.assertEqual(late.node.chain.height, 0)
        late.connect("127.0.0.1", a.port)
        self.assertTrue(wait_until_converged([a, late], timeout=8))
        self.assertEqual(late.node.chain.height, 3)

    def test_transaction_gossip_reaches_all_nodes(self):
        a, b = self._spawn(2)
        b.connect("127.0.0.1", a.port)
        time.sleep(0.3)
        miner = Wallet.generate()
        recipient = Wallet.generate()
        block, _ = a.node.mine_block(miner.address)
        a.announce_block(block)
        self.assertTrue(wait_until_converged([a, b], timeout=8))

        tx = miner.send(a.node.chain, a.node.mempool, recipient.address, 1 * COIN, fee=100)
        a.announce_tx(tx)
        deadline = time.time() + 5
        while time.time() < deadline and tx.txid not in b.node.mempool:
            time.sleep(0.05)
        self.assertIn(tx.txid, b.node.mempool)


class TestMalformedMessageHardening(unittest.TestCase):
    def test_survives_malformed_messages_and_keeps_serving(self):
        # Regression for REVIEW.md #6: a malformed message used to kill the
        # whole peer-reader thread with an uncaught exception.
        node = NetworkNode(Node())
        node.start()
        try:
            sock = socket.create_connection(("127.0.0.1", node.port), timeout=5)
            try:
                sock.sendall((json.dumps({"type": "hello", "port": 1}) + "\n").encode())
                sock.sendall((json.dumps({"type": "block", "data": "not valid hex!!"}) + "\n").encode())
                sock.sendall((json.dumps({"type": "block", "data": "aabbcc"}) + "\n").encode())
                sock.sendall((json.dumps({"type": "tx"}) + "\n").encode())  # missing 'data'
                sock.sendall(b"not even json\n")
                time.sleep(0.3)
                sock.sendall((json.dumps({"type": "get_chain"}) + "\n").encode())
                sock.settimeout(5)
                f = sock.makefile("r")
                line = f.readline()
                self.assertTrue(line, "connection died instead of answering get_chain")
                resp = json.loads(line)
                self.assertEqual(resp["type"], "chain")
                self.assertEqual(len(resp["data"]), 1)  # just genesis
            finally:
                sock.close()
        finally:
            node.stop()


if __name__ == "__main__":
    unittest.main()
