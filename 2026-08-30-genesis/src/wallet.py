"""A wallet: keypair + address, UTXO-scan balance, and transaction building.

Coin selection is intentionally simple (largest-first, greedy accumulate
until the target + fee is covered) — the interesting parts of this project
are the consensus/crypto layers underneath, not a coin-selection algorithm,
so we use the most obviously-correct approach rather than an optimized one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from crypto import KeyPair, hash160, address_to_pubkey_hash
from transaction import Transaction, TxIn, TxOut


@dataclass
class UnspentEntry:
    txid: bytes
    index: int
    output: TxOut


class InsufficientFunds(Exception):
    pass


class Wallet:
    def __init__(self, keypair: Optional[KeyPair] = None):
        self.keypair = keypair or KeyPair.generate()

    @property
    def address(self) -> str:
        return self.keypair.address()

    @property
    def pubkey_hash(self) -> bytes:
        return hash160(self.keypair.pubkey_bytes())

    def utxos(self, utxo_set) -> List[UnspentEntry]:
        mine = []
        for (txid, index), out in utxo_set.items():
            if out.pubkey_hash == self.pubkey_hash:
                mine.append(UnspentEntry(txid, index, out))
        return mine

    def balance(self, utxo_set) -> int:
        return sum(e.output.amount for e in self.utxos(utxo_set))

    def create_transaction(self, utxo_set, to_address: str, amount: int, fee: int) -> Transaction:
        if amount <= 0:
            raise ValueError("amount must be positive")
        if fee < 0:
            raise ValueError("fee must be non-negative")
        candidates = sorted(self.utxos(utxo_set), key=lambda e: e.output.amount, reverse=True)
        needed = amount + fee
        chosen: List[UnspentEntry] = []
        total = 0
        for entry in candidates:
            chosen.append(entry)
            total += entry.output.amount
            if total >= needed:
                break
        if total < needed:
            raise InsufficientFunds(
                f"balance {sum(e.output.amount for e in candidates)} is less than amount+fee {needed}"
            )
        dest_hash = address_to_pubkey_hash(to_address)
        outputs = [TxOut(amount=amount, pubkey_hash=dest_hash)]
        change = total - needed
        if change > 0:
            outputs.append(TxOut(amount=change, pubkey_hash=self.pubkey_hash))
        t = Transaction(
            inputs=[TxIn(prev_txid=e.txid, prev_index=e.index, pubkey=self.keypair.pubkey_bytes())
                    for e in chosen],
            outputs=outputs,
        )
        for i in range(len(chosen)):
            t.sign_input(i, self.keypair.private_key)
        return t
