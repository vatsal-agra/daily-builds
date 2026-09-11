"""The pending-transaction pool: validates incoming transactions against
the live UTXO set, rejects mempool-internal double spends, ranks by fee
for block templates, and revalidates itself after a reorg (a transaction
that was only ever valid because of a now-rolled-back block must not
silently keep sitting in the pool as if it were still spendable).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .chain import Blockchain, ValidationError, UTXOKey
from .script import execute, ScriptError
from .transaction import Transaction


@dataclass
class MempoolEntry:
    tx: Transaction
    fee: int


class Mempool:
    def __init__(self, chain: Blockchain):
        self.chain = chain
        self.entries: Dict[bytes, MempoolEntry] = {}
        self._claimed: Dict[UTXOKey, bytes] = {}  # utxo -> txid claiming it

    def __contains__(self, txid: bytes) -> bool:
        return txid in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    def _validate_against(self, tx: Transaction, extra_claimed: Dict[UTXOKey, bytes]) -> int:
        if tx.is_coinbase():
            raise ValidationError("coinbase transactions do not belong in the mempool")
        fee_in = 0
        for i, txin in enumerate(tx.inputs):
            key = (txin.prev_txid, txin.prev_index)
            claimer = extra_claimed.get(key)
            if claimer is not None and claimer != tx.txid():
                raise ValidationError(f"input {key} already claimed by pending tx {claimer.hex()[:12]}")
            prevout = self.chain.utxo.get(*key)
            if prevout is None:
                raise ValidationError(f"input {key} does not exist in the confirmed UTXO set")
            checker = tx.make_sig_checker(i, prevout.script_pubkey)
            try:
                ok = execute(txin.script_sig, prevout.script_pubkey, checker)
            except ScriptError as e:
                raise ValidationError(f"script error: {e}")
            if not ok:
                raise ValidationError(f"input {i} script did not validate")
            fee_in += prevout.value
        out_total = tx.total_output_value()
        if out_total > fee_in:
            raise ValidationError("transaction spends more than its inputs provide")
        return fee_in - out_total

    def add_transaction(self, tx: Transaction) -> bool:
        txid = tx.txid()
        if txid in self.entries:
            return False
        fee = self._validate_against(tx, self._claimed)
        self.entries[txid] = MempoolEntry(tx, fee)
        for txin in tx.inputs:
            self._claimed[(txin.prev_txid, txin.prev_index)] = txid
        return True

    def remove(self, txid: bytes) -> None:
        entry = self.entries.pop(txid, None)
        if entry is None:
            return
        for txin in entry.tx.inputs:
            key = (txin.prev_txid, txin.prev_index)
            if self._claimed.get(key) == txid:
                del self._claimed[key]

    def remove_confirmed(self, txids: List[bytes]) -> None:
        for txid in txids:
            self.remove(txid)

    def revalidate(self) -> List[bytes]:
        """Re-check every pending tx against the current chain UTXO set
        (call after any reorg). Returns the txids that were dropped.
        """
        dropped = []
        survivors: Dict[bytes, MempoolEntry] = {}
        new_claimed: Dict[UTXOKey, bytes] = {}
        for txid, entry in self.entries.items():
            try:
                fee = self._validate_against(entry.tx, new_claimed)
            except ValidationError:
                dropped.append(txid)
                continue
            survivors[txid] = MempoolEntry(entry.tx, fee)
            for txin in entry.tx.inputs:
                new_claimed[(txin.prev_txid, txin.prev_index)] = txid
        self.entries = survivors
        self._claimed = new_claimed
        return dropped

    def select_for_block(self, max_count: int = 1000) -> List[Transaction]:
        ranked = sorted(self.entries.values(), key=lambda e: e.fee, reverse=True)
        return [e.tx for e in ranked[:max_count]]

    def total_fees(self, txids: List[bytes]) -> int:
        return sum(self.entries[t].fee for t in txids if t in self.entries)
