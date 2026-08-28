"""Helpers to spin up a full simulated network: one shared genesis block
plus N independent `Node`s wired into a full-mesh topology on localhost."""
from __future__ import annotations

from typing import List, Optional, Tuple

from .block import Block, make_genesis_block
from .node import Node
from .transaction import make_coinbase
from .wallet import Wallet

DEFAULT_GENESIS_BITS = 18  # ~262144 hashes/block average -> roughly one block every 1-3s per node
                            # process on typical hardware (see demo.py for the throughput math)
DEFAULT_PREMINE = 1_000_000


def create_network(
    n: int,
    base_port: int = 18500,
    host: str = "127.0.0.1",
    genesis_bits: int = DEFAULT_GENESIS_BITS,
    premine: int = DEFAULT_PREMINE,
    mine: bool = True,
    premine_to_node0: bool = True,
    premine_wallet: Optional[Wallet] = None,
    retarget_enabled: bool = False,
    log=None,
) -> Tuple[List[Node], Wallet]:
    premine_wallet = premine_wallet or Wallet()
    coinbase = make_coinbase(premine_wallet.address, premine, height=0)
    genesis = make_genesis_block(coinbase, genesis_bits)

    nodes: List[Node] = []
    for i in range(n):
        wallet = premine_wallet if (i == 0 and premine_to_node0) else Wallet()
        node = Node(
            name=f"node{i}",
            host=host,
            port=base_port + i,
            genesis=Block.from_dict(genesis.to_dict()),
            genesis_bits=genesis_bits,
            wallet=wallet,
            mine=mine,
            retarget_enabled=retarget_enabled,
            log=log,
        )
        nodes.append(node)

    for node in nodes:
        for other in nodes:
            if other is not node:
                node.add_peer(other.addr)

    return nodes, premine_wallet


def join_network(
    existing: List[Node],
    name: str,
    port: int,
    host: str = "127.0.0.1",
    wallet: Optional[Wallet] = None,
    mine: bool = True,
    retarget_enabled: bool = False,
    log=None,
) -> Node:
    """Add a brand-new node to an already-running network, mid-run —
    used to demonstrate difficulty retargeting responding to a real
    hashrate change (more nodes joining and mining). It bootstraps from
    the exact same genesis block any existing node holds, so it validates
    into the same chain from block zero, and is wired into a full mesh
    with every node already in `existing` (and vice versa)."""
    reference = existing[0]
    genesis_hash = reference.chain.active_chain_hashes()[0]
    genesis = reference.chain.get_block(genesis_hash)
    node = Node(
        name=name, host=host, port=port,
        genesis=Block.from_dict(genesis.to_dict()), genesis_bits=reference.genesis_bits,
        wallet=wallet, mine=mine, retarget_enabled=retarget_enabled, log=log,
    )
    for other in existing:
        node.add_peer(other.addr)
        other.add_peer(node.addr)
    return node


def start_all(nodes: List[Node]) -> None:
    for node in nodes:
        node.start()


def stop_all(nodes: List[Node]) -> None:
    for node in nodes:
        node.stop()


def apply_partition_groups(nodes: List[Node], groups: List[List[str]]) -> None:
    """Split `nodes` into partitions by name. Nodes named in the same
    inner list can talk to each other; nodes in different groups (or not
    named at all -> each its own singleton group) are mutually blocked.
    Pass one group containing every name to heal the network again."""
    name_to_group = {}
    for gi, names in enumerate(groups):
        for nm in names:
            name_to_group[nm] = gi
    next_singleton = len(groups)
    for node in nodes:
        if node.name not in name_to_group:
            name_to_group[node.name] = next_singleton
            next_singleton += 1
    for node in nodes:
        my_group = name_to_group[node.name]
        blocked = {
            other.addr for other in nodes
            if other is not node and name_to_group[other.name] != my_group
        }
        node.set_partition(blocked)
