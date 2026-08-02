"""Shared helpers for spinning up a small real multi-node network in-process
(real TCP sockets, real threads) — used by the demo, the attack simulation,
and the integration tests so the three don't drift."""

import time

from .chain import Blockchain
from .explorer import ExplorerServer
from .mempool import Mempool
from .miner import Miner
from .node import Node


class NetworkHandle:
    def __init__(self, nodes, explorers, miners):
        self.nodes = nodes
        self.explorers = explorers
        self.miners = miners

    def stop(self):
        for m in self.miners:
            m.stop()
        for n in self.nodes:
            n.stop()
        for e in self.explorers:
            e.stop()


def spin_up_network(genesis, count, base_port, host="127.0.0.1", topology="mesh", quiet=True):
    """Starts `count` nodes each with its own P2P port and explorer API,
    connects them per `topology` ('mesh' = every node to every earlier
    node, 'star' = all connect to node 0), and returns a NetworkHandle."""
    nodes, explorers = [], []
    for i in range(count):
        chain = Blockchain(genesis)
        node = Node(host, base_port + i, chain, Mempool(), name=f"node{i}")
        if not quiet:
            node.on_event = lambda msg, i=i: print(f"[node{i}] {msg}")
        node.start()
        explorer = ExplorerServer(node, host=host, port=0)
        explorer.start()
        nodes.append(node)
        explorers.append(explorer)

    for i in range(1, count):
        targets = [0] if topology == "star" else range(i)
        for j in targets:
            nodes[i].connect(host, nodes[j].port)
    time.sleep(0.2)
    return NetworkHandle(nodes, explorers, [])


def tx_is_known(node, txid):
    """True if a node has seen this transaction at all — either still
    pending in its mempool, or already confirmed on its main chain.

    Mining can be fast enough (sub-100ms blocks under light load) to
    confirm a transaction, and prune it out of the mempool, in less time
    than a polling loop's interval — so "is it in the mempool yet" is not
    a safe way to detect "has the network seen this transaction", it can
    transiently and correctly be false on both sides of the pending window.
    """
    if txid in node.mempool:
        return True
    return any(
        tx.txid() == txid
        for h in node.chain.main_chain_hashes()
        for tx in node.chain.blocks_by_hash[h].transactions
    )


def wait_until(predicate, timeout=20.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
