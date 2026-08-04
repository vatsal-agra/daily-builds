"""The pending-transaction pool. A transaction is only accepted if it would
be valid against the chain's *current* UTXO set with every other pending
mempool transaction's claimed inputs treated as already spent — first-seen
mempool double-spend protection, same shape as every real UTXO-chain
mempool.
"""

from bedrock.chain import ChainError


class MempoolError(ValueError):
    pass


class Mempool:
    def __init__(self):
        self.txs = {}       # txid -> Transaction
        self.reserved = set()  # (txid, index) claimed by a pending transaction

    def __len__(self):
        return len(self.txs)

    def __contains__(self, txid: str) -> bool:
        return txid in self.txs

    def add_transaction(self, tx, chain) -> bool:
        """Returns True if newly added, False if already present. Raises
        MempoolError/ChainError (both are ValueError subclasses) if invalid."""
        if tx.is_coinbase:
            raise MempoolError("coinbase transactions cannot enter the mempool")
        if tx.txid in self.txs:
            return False

        for tx_in in tx.inputs:
            key = (tx_in.prev_txid, tx_in.prev_index)
            if key in self.reserved:
                raise MempoolError(f"utxo {key} already claimed by a pending mempool transaction")

        overlay = chain.utxo_set.copy()
        for key in self.reserved:
            overlay.remove(*key)
        chain.apply_transaction(tx, overlay)  # validates; raises ChainError if invalid; mutates only the disposable overlay

        self.txs[tx.txid] = tx
        for tx_in in tx.inputs:
            self.reserved.add((tx_in.prev_txid, tx_in.prev_index))
        return True

    def select_for_block(self, chain, max_count: int = None) -> list:
        """Transactions ordered highest-fee-first (a real, if simplified,
        stand-in for a miner's economic incentive — simplified in that it
        ranks by absolute fee rather than fee *rate*, since nothing here
        tracks serialized transaction size)."""
        ordered = sorted(self.txs.values(), key=chain.transaction_fee, reverse=True)
        return ordered[:max_count] if max_count else ordered

    def rebase(self, chain) -> None:
        """Re-validate every pending transaction against the chain's current
        (possibly just-changed-by-reorg-or-mining) UTXO set, dropping any
        that are now confirmed or conflict. Call after every chain tip
        change."""
        old_txs = list(self.txs.values())
        self.txs = {}
        self.reserved = set()
        for tx in old_txs:
            try:
                self.add_transaction(tx, chain)
            except (MempoolError, ChainError):
                pass

    def drop(self, txid: str) -> None:
        tx = self.txs.pop(txid, None)
        if tx is not None:
            for tx_in in tx.inputs:
                self.reserved.discard((tx_in.prev_txid, tx_in.prev_index))
