"""An in-memory P2P message bus standing in for a real network: it can
drop messages, delay them by a configurable number of "ticks", and split
nodes into partitions that can't reach each other — enough to genuinely
exercise gossip, eventual consistency, and reorg-on-heal, without needing
real sockets for a same-process simulation.
"""

import random


class Bus:
    def __init__(self, drop_rate: float = 0.0, delay_ticks: int = 0, seed=None):
        self.nodes = {}
        self.drop_rate = drop_rate
        self.delay_ticks = delay_ticks
        self.rng = random.Random(seed)
        self.partition_of = {}    # node_id -> partition label; empty dict = one fully-connected network
        self.queue = []           # pending delayed messages: [ticks_left, sender, receiver, msg_type, payload]
        self.events = []          # ('deliver'|'drop', sender_id, receiver_id, msg_type)

    def register(self, node):
        self.nodes[node.id] = node

    def partition(self, groups):
        """groups: iterable of iterables of node ids. Nodes in different
        groups can no longer reach each other until heal() is called."""
        self.partition_of = {}
        for label, group in enumerate(groups):
            for node_id in group:
                self.partition_of[node_id] = label

    def heal(self):
        self.partition_of = {}

    def _connected(self, a, b) -> bool:
        if not self.partition_of:
            return True
        return self.partition_of.get(a) == self.partition_of.get(b)

    def broadcast(self, sender_id, msg_type: str, payload):
        for node_id in self.nodes:
            if node_id == sender_id or not self._connected(sender_id, node_id):
                continue
            if self.rng.random() < self.drop_rate:
                self.events.append(("drop", sender_id, node_id, msg_type))
                continue
            if self.delay_ticks > 0:
                self.queue.append([self.delay_ticks, sender_id, node_id, msg_type, payload])
            else:
                self._deliver(sender_id, node_id, msg_type, payload)

    def _deliver(self, sender_id, receiver_id, msg_type, payload):
        self.events.append(("deliver", sender_id, receiver_id, msg_type))
        self.nodes[receiver_id].handle_message(sender_id, msg_type, payload)

    def pump(self, ticks: int = 1):
        """Advance simulated time, delivering any messages whose delay has
        elapsed. Only needed when delay_ticks > 0."""
        for _ in range(ticks):
            remaining = []
            for item in self.queue:
                item[0] -= 1
                if item[0] <= 0:
                    _, sender_id, receiver_id, msg_type, payload = item
                    self._deliver(sender_id, receiver_id, msg_type, payload)
                else:
                    remaining.append(item)
            self.queue = remaining

    def resync_all(self):
        """Convenience for demo/CLI use after healing a partition: have
        every node pull-sync with every peer it can currently reach, so
        the network reconverges without waiting for fresh gossip traffic."""
        for node_id, node in self.nodes.items():
            for peer_id in self.nodes:
                if peer_id != node_id and self._connected(node_id, peer_id):
                    node.request_sync(peer_id)

    def drain(self):
        """Deliver every still-pending delayed message regardless of its
        remaining tick count (used to settle the network at the end of a
        scripted scenario)."""
        while self.queue:
            self.pump(1)
