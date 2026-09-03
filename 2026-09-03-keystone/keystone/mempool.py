"""The mempool: transactions that have been gossiped and validated against
the current chain tip but aren't in a block yet."""
from __future__ import annotations

from .transaction import Transaction
from .utxo import UTXOSet, ValidationError


class Mempool:
    def __init__(self):
        self.txs = {}  # txid -> Transaction
        self.fees = {}  # txid -> fee

    def __contains__(self, txid: str) -> bool:
        return txid in self.txs

    def __len__(self) -> int:
        return len(self.txs)

    def try_add(self, tx: Transaction, utxo_set: UTXOSet, current_height: int):
        """Validate `tx` against the confirmed UTXO set *and* against
        every other transaction already sitting in the mempool (so two
        mempool transactions can't both spend the same not-yet-confirmed
        output — a double-spend the UTXO set alone wouldn't catch, since
        neither has been applied to it yet). Returns True if accepted."""
        if tx.is_coinbase:
            raise ValidationError("coinbase transactions do not belong in the mempool")
        txid = tx.txid()
        if txid in self.txs:
            return False  # already have it, not an error — just a no-op

        already_spent_in_mempool = set()
        for other in self.txs.values():
            for txin in other.inputs:
                already_spent_in_mempool.add(txin.outpoint)

        for txin in tx.inputs:
            if txin.outpoint in already_spent_in_mempool:
                raise ValidationError(f"conflicts with a transaction already in the mempool: {txin.outpoint}")

        spent_this_block = set()
        fee = utxo_set._validate_transaction(tx, spent_this_block, current_height)

        self.txs[txid] = tx
        self.fees[txid] = fee
        return True

    def remove(self, txid: str) -> None:
        self.txs.pop(txid, None)
        self.fees.pop(txid, None)

    def remove_confirmed(self, block) -> None:
        for tx in block.transactions:
            self.remove(tx.txid())

    def select_for_block(self, max_count: int = None) -> list:
        """Highest-fee-first, all fees strictly non-negative by construction
        (validate_and_apply_block already rejects outputs > inputs)."""
        ordered = sorted(self.txs.values(), key=lambda tx: self.fees[tx.txid()], reverse=True)
        return ordered[:max_count] if max_count is not None else ordered

    def readd_if_valid(self, tx: Transaction, utxo_set: UTXOSet, current_height: int) -> bool:
        """Used after a reorg to try to restore transactions from
        now-orphaned blocks back into the mempool — only if they're still
        actually valid against the new tip (their inputs may have been
        spent by the winning fork instead)."""
        try:
            return self.try_add(tx, utxo_set, current_height)
        except ValidationError:
            return False
