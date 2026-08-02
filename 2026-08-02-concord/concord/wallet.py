"""Keypair management, balance calculation, and transaction building."""

import json
import os

from . import curve
from .transaction import Transaction, TxInput, TxOutput


class InsufficientFunds(Exception):
    pass


class Wallet:
    def __init__(self, private_key=None):
        self.private_key = private_key if private_key is not None else curve.generate_private_key()
        self.public_point = curve.private_to_public(self.private_key)
        self.pubkey_bytes = curve.compress_pubkey(self.public_point)
        self.address = curve.pubkey_to_address(self.public_point)

    def balance(self, utxo: dict) -> int:
        return sum(o.amount for o in utxo.values() if o.address == self.address)

    def my_utxos(self, utxo: dict):
        return [(key, out) for key, out in utxo.items() if out.address == self.address]

    def build_transaction(self, utxo: dict, to_address: str, amount: int, fee: int = 0) -> Transaction:
        if amount <= 0:
            raise ValueError("amount must be positive")
        candidates = self.my_utxos(utxo)
        candidates.sort(key=lambda kv: kv[1].amount, reverse=True)
        selected = []
        total = 0
        needed = amount + fee
        for key, out in candidates:
            selected.append((key, out))
            total += out.amount
            if total >= needed:
                break
        if total < needed:
            raise InsufficientFunds(f"have {total}, need {needed}")

        inputs = [TxInput(txid, index, pubkey=self.pubkey_bytes) for (txid, index) in
                  [k for k, _ in selected]]
        outputs = [TxOutput(amount, to_address)]
        change = total - needed
        if change > 0:
            outputs.append(TxOutput(change, self.address))

        tx = Transaction(inputs, outputs)
        for i in range(len(inputs)):
            tx.sign_input(i, self.private_key)
        return tx

    def to_dict(self):
        return {"private_key": hex(self.private_key)}

    @staticmethod
    def from_dict(d):
        return Wallet(int(d["private_key"], 16))

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @staticmethod
    def load(path):
        with open(path) as f:
            return Wallet.from_dict(json.load(f))

    @staticmethod
    def load_or_create(path):
        if os.path.exists(path):
            return Wallet.load(path)
        w = Wallet()
        w.save(path)
        return w
