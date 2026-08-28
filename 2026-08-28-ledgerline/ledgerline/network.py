"""Helpers to spin up a full simulated network: one shared genesis block
plus N independent `Node`s wired into a full-mesh topology on localhost."""
from __future__ import annotations

import multiprocessing
import time
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


def _mining_process_main(
    genesis_dict: dict, genesis_bits: int, name: str, host: str, port: int,
    peer_addrs: List[Tuple[str, int]], retarget_enabled: bool,
) -> None:
    """Entry point run inside a real separate OS process by
    `spawn_mining_process`. Deliberately NOT an in-process thread: CPython's
    GIL caps total hashing throughput across concurrent threads in one
    process to roughly what a single thread gets, no matter how many
    threads you add — a fresh OS process gets its own interpreter and its
    own GIL, so this is what actually adds parallel hash power rather than
    just adding contention. Nodes only ever talk over real TCP sockets, so
    a mining node genuinely doesn't care whether its peers live in this
    process or a different one."""
    node = Node(
        name=name, host=host, port=port,
        genesis=Block.from_dict(genesis_dict), genesis_bits=genesis_bits,
        wallet=Wallet(), mine=True, retarget_enabled=retarget_enabled, log=None,
    )
    for addr in peer_addrs:
        node.add_peer(tuple(addr))
    node.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    node.stop()


def spawn_mining_process(
    genesis_block: Block, genesis_bits: int, name: str, port: int,
    peer_addrs: List[Tuple[str, int]], host: str = "127.0.0.1", retarget_enabled: bool = False,
) -> multiprocessing.Process:
    """Start a mining node in a real separate OS process — see
    `_mining_process_main`. Returns the live `multiprocessing.Process`;
    call `.terminate()` (then `.join()`) to stop it. The caller is
    responsible for wiring the *other* side of the peer relationship too
    (e.g. `existing_node.add_peer((host, port))`) since this process's
    node only learns about the peers it's told about here."""
    proc = multiprocessing.Process(
        target=_mining_process_main,
        args=(genesis_block.to_dict(), genesis_bits, name, host, port, list(peer_addrs), retarget_enabled),
        daemon=True,
    )
    proc.start()
    return proc


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
