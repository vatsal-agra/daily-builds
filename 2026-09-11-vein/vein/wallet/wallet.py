"""A simple single-key wallet: key management, coin selection, and
building + signing a real spend transaction against a node's live UTXO
view (fetched over RPC, not trusted blindly — see wallet CLI usage).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Tuple

from ..crypto.ecdsa import generate_privkey
from ..crypto.curve import derive_pubkey
from ..crypto.address import serialize_pubkey, address_from_pubkey, pubkey_hash_from_address
from ..crypto.hashes import hash160
from ..core.transaction import Transaction, TxIn, TxOut
from ..core.script import Script

INSUFFICIENT_FUNDS = "insufficient funds"


class InsufficientFunds(Exception):
    pass


@dataclass
class Wallet:
    privkey: int

    @property
    def pubkey_bytes(self) -> bytes:
        return serialize_pubkey(derive_pubkey(self.privkey))

    @property
    def pubkey_hash(self) -> bytes:
        return hash160(self.pubkey_bytes)

    @property
    def address(self) -> str:
        return address_from_pubkey(self.pubkey_bytes)

    @staticmethod
    def generate() -> "Wallet":
        return Wallet(generate_privkey())

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({"privkey": hex(self.privkey), "address": self.address}, f, indent=2)
        os.chmod(path, 0o600)

    @staticmethod
    def load(path: str) -> "Wallet":
        with open(path) as f:
            data = json.load(f)
        return Wallet(int(data["privkey"], 16))

    def select_coins(self, utxos: List[Tuple[Tuple[bytes, int], TxOut]], amount: int, fee: int
                      ) -> Tuple[List[Tuple[Tuple[bytes, int], TxOut]], int]:
        """Simple largest-first coin selection."""
        need = amount + fee
        chosen = []
        total = 0
        for key, txout in sorted(utxos, key=lambda kv: -kv[1].value):
            chosen.append((key, txout))
            total += txout.value
            if total >= need:
                return chosen, total - need
        raise InsufficientFunds(f"{INSUFFICIENT_FUNDS}: need {need}, have {total}")

    def build_transaction(self, utxos: List[Tuple[Tuple[bytes, int], TxOut]],
                           to_pubkey_hash: bytes, amount: int, fee: int) -> Transaction:
        if amount <= 0:
            raise ValueError("amount must be positive")
        chosen, change = self.select_coins(utxos, amount, fee)
        inputs = [TxIn(txid, idx, Script([])) for (txid, idx), _ in chosen]
        outputs = [TxOut(amount, Script.p2pkh_lock(to_pubkey_hash))]
        if change > 0:
            outputs.append(TxOut(change, Script.p2pkh_lock(self.pubkey_hash)))
        tx = Transaction(inputs, outputs)
        for i, (_, prevout) in enumerate(chosen):
            tx.sign_input(i, self.privkey, prevout.script_pubkey, self.pubkey_bytes)
        return tx
