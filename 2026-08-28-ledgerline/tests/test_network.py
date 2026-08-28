"""Integration tests over a real multi-node network on real localhost TCP
sockets — the only way to honestly test gossip, mining races, and reorgs."""
import time
import unittest

from ledgerline.network import apply_partition_groups, create_network, start_all, stop_all

BITS = 16  # cheap but not so cheap that 3 threads spam the CPU pointlessly for this test


def wait_until(predicate, timeout=30, interval=0.15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestNetwork(unittest.TestCase):
    def setUp(self):
        self._port_counter = getattr(TestNetwork, "_next_port", 21000)
        TestNetwork._next_port = self._port_counter + 20

    def _network(self, n, **kwargs):
        nodes, premine = create_network(n, base_port=self._port_counter, genesis_bits=BITS, **kwargs)
        self.addCleanup(stop_all, nodes)
        return nodes, premine

    def test_nodes_mine_and_converge(self):
        nodes, _ = self._network(3)
        start_all(nodes)
        ok = wait_until(lambda: all(n.status()["height"] >= 2 for n in nodes), timeout=40)
        self.assertTrue(ok, "network failed to mine 2 blocks")
        ok = wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=20)
        self.assertTrue(ok, "network failed to converge on one tip")
        for n in nodes:
            self.assertEqual(n.chain.tip, nodes[0].chain.tip)

    def test_full_mesh_connects_every_pair(self):
        nodes, _ = self._network(4, mine=False)
        start_all(nodes)
        ok = wait_until(lambda: all(n.peer_count() == 3 for n in nodes), timeout=15)
        self.assertTrue(ok, f"not fully connected: {[n.peer_count() for n in nodes]}")

    def test_transaction_propagates_and_confirms(self):
        nodes, premine_wallet = self._network(3)
        start_all(nodes)
        wait_until(lambda: all(n.status()["height"] >= 2 for n in nodes), timeout=40)
        wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=20)

        sender = nodes[0]
        self.assertEqual(sender.wallet.address, premine_wallet.address)
        receiver = nodes[1].wallet.address
        starting = sender.chain.balance_of(receiver)
        tx = sender.wallet.create_transaction(sender.chain, receiver, 100, 1, mempool=sender.mempool)
        ok, err = sender.submit_transaction(tx)
        self.assertTrue(ok, err)

        confirmed = wait_until(
            lambda: all(n.chain.balance_of(receiver) >= starting + 100 for n in nodes), timeout=40
        )
        self.assertTrue(confirmed, "transaction never confirmed on all nodes")

    def test_partition_forks_and_heal_reconverges(self):
        nodes, _ = self._network(4)
        start_all(nodes)
        wait_until(lambda: all(n.status()["height"] >= 2 for n in nodes), timeout=40)
        wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=20)

        names = [n.name for n in nodes]
        group_a, group_b = names[:2], names[2:]
        apply_partition_groups(nodes, [group_a, group_b])

        a0, b0 = nodes[0].status()["height"], nodes[2].status()["height"]
        grew = wait_until(
            lambda: nodes[0].status()["height"] > a0 and nodes[2].status()["height"] > b0, timeout=40
        )
        self.assertTrue(grew, "both partitions should keep mining independently")
        self.assertNotEqual(nodes[0].chain.tip, nodes[2].chain.tip, "partitions should have diverged")

        apply_partition_groups(nodes, [names])
        converged = wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=40)
        self.assertTrue(converged, "network should reconverge after healing")
        winner = nodes[0].chain.tip
        for n in nodes:
            self.assertEqual(n.chain.tip, winner)
            self.assertEqual(n.chain.cum_work[n.chain.tip], nodes[0].chain.cum_work[winner])


if __name__ == "__main__":
    unittest.main()
