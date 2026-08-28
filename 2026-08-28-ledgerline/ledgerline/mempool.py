"""Pending-transaction pool. Miners draw block templates from here, highest
fee-per-byte first (approximated here as fee-per-input, since transactions
are small canonical-JSON blobs rather than wire-optimized bytes)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .transaction import Transaction


class Mempool:
    def __init__(self):
        self.txs: Dict[str, Transaction] = {}
        self.fees: Dict[str, int] = {}

    def __len__(self) -> int:
        return len(self.txs)

    def contains(self, txid: str) -> bool:
        return txid in self.txs

    def add(self, tx: Transaction, fee: int) -> None:
        self.txs[tx.txid()] = tx
        self.fees[tx.txid()] = fee

    def remove(self, txid: str) -> None:
        self.txs.pop(txid, None)
        self.fees.pop(txid, None)

    def remove_many(self, txids) -> None:
        for txid in txids:
            self.remove(txid)

    def select_for_block(self, max_count: Optional[int] = None) -> List[Transaction]:
        """Highest-fee-first selection, skipping any transaction whose
        inputs conflict with one already selected (can't spend the same
        coin twice in one block)."""
        if max_count is not None and max_count <= 0:
            return []
        ordered = sorted(self.txs.values(), key=lambda t: self.fees.get(t.txid(), 0), reverse=True)
        chosen: List[Transaction] = []
        used_inputs: set = set()
        for tx in ordered:
            keys = {(i.prev_txid, i.prev_index) for i in tx.inputs}
            if keys & used_inputs:
                continue
            chosen.append(tx)
            used_inputs |= keys
            if max_count is not None and len(chosen) >= max_count:
                break
        return chosen

    def snapshot(self) -> List[Tuple[str, int, int]]:
        """(txid, fee, num_outputs) for display in the explorer."""
        return [(txid, self.fees.get(txid, 0), len(tx.outputs)) for txid, tx in self.txs.items()]
