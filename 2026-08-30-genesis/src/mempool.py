"""The mempool: transactions waiting to be mined, with fee-priority selection.

Deliberately simple about unconfirmed chains: a mempool transaction may
only spend outputs that are already confirmed on the active chain (no
spending another pending transaction's not-yet-mined output). That keeps
"is this transaction currently valid" a pure question about `Blockchain`'s
UTXO set plus "does anything else in the mempool already claim this
input", with no separate unconfirmed-ancestor bookkeeping.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from transaction import Transaction

Outpoint = Tuple[bytes, int]


class Mempool:
    def __init__(self):
        self.txs: Dict[bytes, Transaction] = {}       # txid -> tx
        self._spent_by_pending: Dict[Outpoint, bytes] = {}  # outpoint -> txid claiming it

    def __len__(self) -> int:
        return len(self.txs)

    def __contains__(self, txid: bytes) -> bool:
        return txid in self.txs

    def add_transaction(self, t: Transaction, utxo_lookup) -> Tuple[bool, str]:
        txid = t.txid()
        if txid in self.txs:
            return False, "already in mempool"
        if t.is_coinbase():
            return False, "coinbase transactions cannot enter the mempool"
        for txin in t.inputs:
            outpoint = (txin.prev_txid, txin.prev_index)
            if outpoint in self._spent_by_pending:
                return False, f"conflicts with pending tx {self._spent_by_pending[outpoint].hex()[:10]} (double-spend)"
        ok, reason = t.verify(utxo_lookup)
        if not ok:
            return False, reason
        fee = t.fee(utxo_lookup)
        if fee < 0:
            return False, "negative fee"
        self.txs[txid] = t
        for txin in t.inputs:
            self._spent_by_pending[(txin.prev_txid, txin.prev_index)] = txid
        return True, "ok"

    def remove_confirmed(self, block_txs: List[Transaction]) -> None:
        """Drop transactions that were just mined into a block, and any
        remaining pending transaction that now conflicts (double-spends
        something the newly mined block already spent) — this matters after
        a reorg replays a different set of blocks."""
        confirmed_ids = {t.txid() for t in block_txs}
        confirmed_outpoints = set()
        for t in block_txs:
            for txin in t.inputs:
                confirmed_outpoints.add((txin.prev_txid, txin.prev_index))
        for txid in list(self.txs):
            t = self.txs[txid]
            spends = {(i.prev_txid, i.prev_index) for i in t.inputs}
            if txid in confirmed_ids or spends & confirmed_outpoints:
                self._drop(txid)

    def _drop(self, txid: bytes) -> None:
        t = self.txs.pop(txid, None)
        if t is None:
            return
        for txin in t.inputs:
            key = (txin.prev_txid, txin.prev_index)
            if self._spent_by_pending.get(key) == txid:
                del self._spent_by_pending[key]

    def revalidate(self, utxo_lookup) -> None:
        """Re-check every pending tx against current chain state (called
        after a reorg, since the UTXO set the mempool was validated against
        may no longer be the active one)."""
        for txid in list(self.txs):
            t = self.txs[txid]
            ok, _ = t.verify(utxo_lookup)
            if not ok:
                self._drop(txid)

    def select_for_block(self, utxo_lookup, max_count: Optional[int] = None) -> List[Transaction]:
        """Fee-rate-first (fee / serialized size) selection — same greedy
        approach real miners use to maximize revenue per byte of block space."""
        scored = []
        for t in self.txs.values():
            fee = t.fee(utxo_lookup)
            size = max(1, len(t.serialize()))
            scored.append((fee / size, t))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        chosen = [t for _, t in scored]
        if max_count is not None:
            chosen = chosen[:max_count]
        return chosen
