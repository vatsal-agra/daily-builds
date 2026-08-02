"""Pending-transaction pool with double-spend rejection.

A transaction is accepted only if every input references an unspent
output in the given UTXO snapshot, no two inputs (across the whole pool,
including the incoming tx) reference the same outpoint, and every
input's signature checks out against the pubkey that hashes to the
UTXO's owning address.
"""

from .transaction import Transaction


class MempoolRejected(Exception):
    pass


class Mempool:
    def __init__(self):
        self.transactions = {}       # txid -> Transaction
        self._spent_outpoints = {}   # (txid, index) -> spender txid, across the pool

    def _validate_against(self, tx: Transaction, utxo: dict):
        if tx.is_coinbase:
            raise MempoolRejected("coinbase transactions cannot enter the mempool")
        if not tx.inputs:
            raise MempoolRejected("transaction has no inputs")
        seen_here = set()
        total_in = 0
        for i, inp in enumerate(tx.inputs):
            key = (inp.txid, inp.index)
            if key in seen_here:
                raise MempoolRejected(f"tx double-spends its own input {key}")
            seen_here.add(key)
            if key in self._spent_outpoints:
                raise MempoolRejected(f"input {key} already spent by a pending transaction")
            utxo_entry = utxo.get(key)
            if utxo_entry is None:
                raise MempoolRejected(f"input {key} does not reference a known unspent output")
            if not tx.verify_input_signature(i):
                raise MempoolRejected(f"invalid signature on input {i}")
            from . import curve
            point = curve.decompress_pubkey(inp.pubkey)
            if curve.pubkey_to_address(point) != utxo_entry.address:
                raise MempoolRejected(f"input {i} pubkey does not match UTXO owner")
            total_in += utxo_entry.amount
        total_out = tx.total_output()
        if total_out > total_in:
            raise MempoolRejected(
                f"outputs ({total_out}) exceed inputs ({total_in})"
            )
        return total_in - total_out  # fee

    def add_transaction(self, tx: Transaction, utxo: dict) -> int:
        """Raises MempoolRejected on any validation failure; returns the fee
        on success. Idempotent for a transaction already in the pool."""
        if tx.txid() in self.transactions:
            return 0
        fee = self._validate_against(tx, utxo)
        self.transactions[tx.txid()] = tx
        for inp in tx.inputs:
            self._spent_outpoints[(inp.txid, inp.index)] = tx.txid()
        return fee

    def remove_confirmed(self, txids):
        for txid in txids:
            tx = self.transactions.pop(txid, None)
            if tx is None:
                continue
            for inp in tx.inputs:
                self._spent_outpoints.pop((inp.txid, inp.index), None)

    def prune_conflicts(self, utxo: dict):
        """Drop any pooled transaction that spends an outpoint no longer in
        the UTXO set — i.e. a losing side of a double-spend whose rival
        just got confirmed. Without this a "ghost" transaction that can
        never be mined again would sit in the pool indefinitely instead of
        being visibly, permanently rejected the moment its rival wins."""
        dropped = []
        for txid, tx in list(self.transactions.items()):
            if any((inp.txid, inp.index) not in utxo for inp in tx.inputs):
                dropped.append(txid)
        for txid in dropped:
            tx = self.transactions.pop(txid)
            for inp in tx.inputs:
                self._spent_outpoints.pop((inp.txid, inp.index), None)
        return dropped

    def reintroduce(self, txs, utxo: dict):
        """Best-effort re-add of transactions orphaned by a reorg. Ones that
        conflict with the new chain's state are silently dropped, not errored —
        that's the expected outcome for a transaction the winning chain
        already double-spent around."""
        restored = []
        for tx in txs:
            try:
                self.add_transaction(tx, utxo)
                restored.append(tx.txid())
            except MempoolRejected:
                pass
        return restored

    def select_for_block(self, max_count=None):
        """Highest-fee-first selection (fees aren't tracked post-insertion
        here, so this orders by fee computed fresh isn't available without
        utxo; callers with a utxo snapshot should sort externally. This
        default preserves insertion order, which is FIFO fairness)."""
        txs = list(self.transactions.values())
        return txs if max_count is None else txs[:max_count]

    def __contains__(self, txid):
        return txid in self.transactions

    def __len__(self):
        return len(self.transactions)
