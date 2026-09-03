"""FullNode: wires a Blockchain + Mempool + P2P Network + an optional
background miner thread into one runnable node."""
from __future__ import annotations

import threading

from . import miner as miner_module
from .mempool import Mempool
from .network import Node
from .transaction import Transaction
from .utxo import ValidationError


class FullNode:
    def __init__(self, host: str, port: int, chain, miner_wallet=None, name: str = None):
        self.chain = chain
        self.mempool = Mempool()
        self.net = Node(host, port, self.chain, self.mempool, name=name)
        self.miner_wallet = miner_wallet

        self.mining = False
        self._miner_thread = None
        self._extra_nonce = 0
        self.blocks_mined = 0

    # ------------------------------------------------------------------
    def start(self) -> None:
        self.net.start()

    def stop(self) -> None:
        self.mining = False
        if self._miner_thread is not None:
            self._miner_thread.join(timeout=5.0)
        self.net.stop()

    def connect_to(self, host: str, port: int) -> bool:
        return self.net.connect_to(host, port)

    # ------------------------------------------------------------------
    def submit_transaction(self, tx: Transaction) -> bool:
        with self.net.lock:
            txid = tx.txid()
            if txid in self.net.known_txs:
                return False
            self.net.known_txs.add(txid)
            self.net.tx_store[txid] = tx
            try:
                accepted = self.mempool.try_add(tx, self.chain.utxo_set, self.chain.height())
            except ValidationError:
                accepted = False
        if accepted:
            self.net.announce_tx(tx)
        return accepted

    # ------------------------------------------------------------------
    def start_mining(self) -> None:
        if self.miner_wallet is None:
            raise ValueError("node has no miner_wallet configured")
        if self.mining:
            return
        self.mining = True
        self._miner_thread = threading.Thread(target=self._mine_loop, daemon=True, name=f"{self.net.name}-miner")
        self._miner_thread.start()

    def stop_mining(self) -> None:
        self.mining = False

    def _mine_loop(self) -> None:
        while self.mining:
            with self.net.lock:
                tip_before = self.chain.tip_hash
            self._extra_nonce += 1
            extra_nonce = self._extra_nonce

            def should_stop(tip_before=tip_before):
                return (not self.mining) or self.chain.tip_hash != tip_before

            block = miner_module.mine_block(
                self.chain, self.mempool, self.miner_wallet,
                extra_nonce=extra_nonce, max_nonce=1 << 32, should_stop=should_stop,
            )
            if block is None:
                continue  # stop requested, or a competing block changed the tip mid-search

            with self.net.lock:
                if self.chain.tip_hash != tip_before:
                    continue  # tip moved while we were mining; template is stale, retry
                result = self.chain.add_block(block, self.mempool)
            if result["accepted"]:
                self.blocks_mined += 1
                self.net.announce_block(block)
