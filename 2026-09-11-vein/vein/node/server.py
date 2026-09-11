"""Wires chain + mempool + P2P + miner + RPC into one runnable node process."""

from __future__ import annotations

from ..core.chain import Blockchain, ChainParams
from ..core.mempool import Mempool
from .p2p import P2PNode
from .miner import Miner
from .rpc import RPCServer


class VeinNode:
    def __init__(self, params: ChainParams, p2p_host: str, p2p_port: int,
                 rpc_host: str, rpc_port: int, miner_pubkey_hash: bytes,
                 node_name: str = "node"):
        self.chain = Blockchain(params)
        self.mempool = Mempool(self.chain)
        self.p2p = P2PNode(self.chain, self.mempool, p2p_host, p2p_port, node_name=node_name)
        self.miner = Miner(self.chain, self.mempool, miner_pubkey_hash, self.p2p.submit_block,
                            node_name=node_name)
        self.rpc = RPCServer(self.p2p, self.chain, self.mempool, self.miner, rpc_host, rpc_port)

        self.p2p.on_new_tip.append(lambda tip: self.miner.notify_new_work())

    def start(self, mine: bool = False) -> None:
        self.p2p.start()
        self.rpc.start()
        if mine:
            self.miner.start()

    def stop(self) -> None:
        self.miner.stop()
        self.p2p.stop()
        self.rpc.stop()
