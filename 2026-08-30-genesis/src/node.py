"""A full node: chain + mempool + wallet + gossip message handlers.

Wires the pieces (`Blockchain`, `Mempool`, `Wallet`) into something that
behaves like one participant on the simulated P2P network: it can attempt
to mine (bounded by a per-round nonce budget, which is how relative
hashpower is modeled — see `network.py`'s docstring for why the network
itself is a deterministic simulation rather than real sockets), and it
reacts to gossiped blocks/transactions from peers by validating them
against its own chain and re-broadcasting anything new.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from block import Block
from blockchain import Blockchain, subsidy_at
from mempool import Mempool
from transaction import Transaction
from wallet import Wallet


@dataclass
class NodeStats:
    blocks_mined: int = 0
    blocks_accepted_from_peers: int = 0
    blocks_rejected: int = 0
    reorgs_seen: int = 0
    txs_relayed: int = 0


class Node:
    def __init__(self, name: str, blockchain: Blockchain, network, wallet: Optional[Wallet] = None):
        self.name = name
        self.chain = blockchain
        self.mempool = Mempool()
        self.wallet = wallet or Wallet()
        self.network = network
        self.stats = NodeStats()
        self.log: List[str] = []
        network.register(name, self._on_message)

    # -- outbound: mining & submitting -------------------------------------
    def attempt_mine(self, nonce_budget: int, timestamp: int) -> Optional[Block]:
        prev = self.chain.tip
        height = self.chain.heights[prev] + 1
        target = self.chain.next_expected_target()
        utxo = self.chain.utxo_set()
        lookup = lambda txid, idx: utxo.get((txid, idx))
        txs = self.mempool.select_for_block(lookup)
        total_fees = sum(t.fee(lookup) for t in txs)
        coinbase = Transaction.coinbase(self.wallet.pubkey_hash, subsidy_at(height) + total_fees, height)
        block = Block.new(prev_hash=prev, transactions=[coinbase] + txs, target=target, timestamp=timestamp)
        nonce = block.mine(max_nonce=nonce_budget)
        if nonce is None:
            return None
        result = self.chain.accept_block(block, now=timestamp)
        if not result.accepted:
            # Should not happen for a block we just built ourselves against
            # our own tip, but never silently drop a bug: surface it.
            self.log.append(f"BUG: self-mined block rejected: {result.reason}")
            return None
        self.stats.blocks_mined += 1
        self.mempool.remove_confirmed(block.transactions)
        self.log.append(f"mined block {block.block_hash_hex()[:10]} at height {height}")
        self.network.broadcast(self.name, "block", block)
        return block

    def announce_chain(self) -> None:
        """Re-broadcast every main-chain block to peers, in order.

        Used to (re)synchronize after a network partition heals: a
        simplified stand-in for Bitcoin's request-based initial-block-
        download (getheaders/getdata) that reaches the same end state
        (every peer eventually sees every block) through the same
        `accept_block` validation path each block already goes through —
        a peer that already has a given block just reports "duplicate"
        and moves on."""
        for h in self.chain.main_chain_hashes():
            self.network.broadcast(self.name, "block", self.chain.blocks[h])

    def submit_transaction(self, t: Transaction) -> tuple:
        utxo = self.chain.utxo_set()
        lookup = lambda txid, idx: utxo.get((txid, idx))
        ok, reason = self.mempool.add_transaction(t, lookup)
        if ok:
            self.network.broadcast(self.name, "tx", t)
        return ok, reason

    # -- inbound: gossip handlers -------------------------------------------
    def _on_message(self, sender: str, kind: str, payload: object) -> None:
        if kind == "block":
            self._on_block(sender, payload)
        elif kind == "tx":
            self._on_tx(sender, payload)

    def _on_block(self, sender: str, block: Block) -> None:
        bh = block.block_hash()
        if bh in self.chain.blocks:
            return  # already known — do not re-broadcast, avoids gossip storms
        result = self.chain.accept_block(block)
        if not result.accepted:
            self.stats.blocks_rejected += 1
            self.log.append(f"rejected block {bh.hex()[:10]} from {sender}: {result.reason}")
            return
        self.stats.blocks_accepted_from_peers += 1
        if result.reorged:
            self.stats.reorgs_seen += 1
            self.log.append(f"REORG onto {result.new_tip.hex()[:10]} (via block from {sender})")
            self.mempool.revalidate(lambda txid, idx: self.chain.utxo_set().get((txid, idx)))
        self.mempool.remove_confirmed(block.transactions)
        self.log.append(f"accepted block {bh.hex()[:10]} from {sender} (height {self.chain.heights[bh]})")
        self.network.broadcast(self.name, "block", block)  # gossip onward

    def _on_tx(self, sender: str, t: Transaction) -> None:
        txid = t.txid()
        if txid in self.mempool:
            return
        utxo = self.chain.utxo_set()
        ok, reason = self.mempool.add_transaction(t, lambda a, b: utxo.get((a, b)))
        if ok:
            self.stats.txs_relayed += 1
            self.network.broadcast(self.name, "tx", t)  # gossip onward
