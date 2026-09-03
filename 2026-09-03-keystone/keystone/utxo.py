"""The UTXO set: which transaction outputs currently exist and are
unspent. This is "whose money is this" — the ledger state every node must
independently compute and agree on."""
from __future__ import annotations

from . import script
from .block import Block
from .transaction import Transaction

COINBASE_MATURITY = 2  # blocks a coinbase output must wait before it's spendable
# See REVIEW.md: without this, a reorg that undoes the block containing a
# coinbase can retroactively invalidate a transaction several blocks later
# that already spent it — money that was "confirmed" turns out to have never
# existed on the winning chain.


class ValidationError(ValueError):
    pass


class UTXOSet:
    def __init__(self):
        self.utxos = {}  # (txid, index) -> (TxOut, height_created, is_coinbase)

    def get(self, txid: str, index: int):
        entry = self.utxos.get((txid, index))
        return entry[0] if entry else None

    def balance_of(self, pubkey_hash: bytes) -> int:
        total = 0
        target = ["OP_DUP", "OP_HASH160", pubkey_hash.hex(), "OP_EQUALVERIFY", "OP_CHECKSIG"]
        for txout, _height, _coinbase in self.utxos.values():
            if txout.script_pubkey == target:
                total += txout.amount
        return total

    def snapshot(self) -> dict:
        return dict(self.utxos)

    def restore(self, snapshot: dict) -> None:
        self.utxos = dict(snapshot)

    def _validate_transaction(self, tx: Transaction, spent_this_block: set, current_height: int):
        """Returns fee (int) on success, raises ValidationError otherwise.
        Mutates nothing; `spent_this_block` is only read from + written to
        by the caller so intra-block double-spends are caught before any
        real state changes."""
        if not tx.inputs:
            # A non-coinbase transaction with zero inputs would sail
            # through the total_out > total_in check below whenever it also
            # has zero outputs (0 > 0 is False) — a degenerate, useless-but-
            # "valid" empty transaction that serves no purpose but to pad
            # the chain with junk txids. Reject it outright instead. Found
            # by adversarial review; see REVIEW.md.
            raise ValidationError("non-coinbase transaction must have at least one input")

        sighash = tx.signing_hash()
        total_in = 0
        for txin in tx.inputs:
            outpoint = txin.outpoint
            if outpoint in spent_this_block:
                raise ValidationError(f"double-spend within block: {outpoint}")
            entry = self.utxos.get(outpoint)
            if entry is None:
                raise ValidationError(f"input references missing/already-spent output {outpoint}")
            prev_out, created_height, is_coinbase = entry
            if is_coinbase and current_height - created_height < COINBASE_MATURITY:
                raise ValidationError(
                    f"immature coinbase spend: output at height {created_height}, "
                    f"needs {COINBASE_MATURITY} confirmations, chain is at {current_height}"
                )
            if not script.execute(txin.script_sig, prev_out.script_pubkey, sighash):
                raise ValidationError(f"script verification failed for input {outpoint}")
            spent_this_block.add(outpoint)
            total_in += prev_out.amount
        total_out = tx.total_output()
        if total_out > total_in:
            raise ValidationError(f"outputs ({total_out}) exceed inputs ({total_in})")
        if any(o.amount < 0 for o in tx.outputs):
            raise ValidationError("negative output amount")
        return total_in - total_out

    def validate_and_apply_block(self, block: Block, block_reward: int):
        """Full validation + state mutation for one block, all-or-nothing.
        Returns the list of (outpoint, txout, height, is_coinbase) tuples
        removed from the UTXO set, so the caller can undo this exact block
        later (needed for reorgs). Raises ValidationError and leaves the
        UTXO set completely unchanged if anything is invalid."""
        if not block.transactions or not block.transactions[0].is_coinbase:
            raise ValidationError("block's first transaction must be coinbase")
        for tx in block.transactions[1:]:
            if tx.is_coinbase:
                raise ValidationError("only the first transaction may be coinbase")

        txids_seen = set()
        for tx in block.transactions:
            txid = tx.txid()
            if txid in txids_seen:
                raise ValidationError(f"duplicate txid within block: {txid}")
            txids_seen.add(txid)

        spent_this_block = set()
        total_fees = 0
        for tx in block.transactions[1:]:
            total_fees += self._validate_transaction(tx, spent_this_block, block.height)

        coinbase_tx = block.transactions[0]
        if any(o.amount < 0 for o in coinbase_tx.outputs):
            # A negative coinbase output was never actually rejected by the
            # `coinbase_out > reward + fees` check below on its own — a
            # negative total trivially satisfies "not greater than" a
            # positive reward, so this needs its own explicit check. Found
            # by adversarial review; see REVIEW.md.
            raise ValidationError("coinbase output amount cannot be negative")
        coinbase_out = coinbase_tx.total_output()
        if coinbase_out > block_reward + total_fees:
            raise ValidationError(
                f"coinbase pays out {coinbase_out}, but reward+fees is only {block_reward + total_fees}"
            )

        # Everything validated — now actually mutate state.
        removed = []
        for outpoint in spent_this_block:
            entry = self.utxos.pop(outpoint)
            removed.append((outpoint[0], outpoint[1], entry[0], entry[1], entry[2]))

        for tx in block.transactions:
            txid = tx.txid()
            is_coinbase = tx.is_coinbase
            for index, txout in enumerate(tx.outputs):
                self.utxos[(txid, index)] = (txout, block.height, is_coinbase)

        return removed

    def undo_block(self, block: Block, removed) -> None:
        """Reverse validate_and_apply_block: drop this block's own outputs,
        restore whatever it spent."""
        for tx in block.transactions:
            txid = tx.txid()
            for index in range(len(tx.outputs)):
                self.utxos.pop((txid, index), None)
        for txid, index, txout, height, is_coinbase in removed:
            self.utxos[(txid, index)] = (txout, height, is_coinbase)
