"""A wallet: a keypair, its derived address, and helpers to check balance
and build spends against a given chain (+ optionally avoid double-spending
against the local mempool)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from . import ecdsa
from .crypto import pubkey_to_address
from .mempool import Mempool
from .transaction import Transaction, build_transaction


class InsufficientFunds(Exception):
    pass


class Wallet:
    def __init__(self, privkey: Optional[int] = None):
        self.privkey = privkey if privkey is not None else ecdsa.generate_private_key()
        self.pubkey = ecdsa.private_to_public(self.privkey)
        self.address = pubkey_to_address(ecdsa.compress_pubkey(self.pubkey))

    def balance(self, chain) -> int:
        return chain.balance_of(self.address)

    def create_transaction(
        self,
        chain,
        to_address: str,
        amount: int,
        fee: int = 1,
        mempool: Optional[Mempool] = None,
        change_address: Optional[str] = None,
    ) -> Transaction:
        available = chain.utxos_for(self.address)
        if mempool is not None:
            already_spent = {
                (i.prev_txid, i.prev_index)
                for tx in mempool.txs.values()
                for i in tx.inputs
            }
            available = [u for u in available if (u[0], u[1]) not in already_spent]
        available.sort(key=lambda u: u[2], reverse=True)  # largest-first, keeps input count small

        picked: List[Tuple[str, int, int]] = []
        total = 0
        for u in available:
            picked.append(u)
            total += u[2]
            if total >= amount + fee:
                break
        if total < amount + fee:
            raise InsufficientFunds(
                f"{self.address[:12]}... has {chain.balance_of(self.address)}, "
                f"needs {amount + fee} (amount {amount} + fee {fee})"
            )
        return build_transaction(
            picked, self.privkey, to_address, amount, fee, change_address or self.address
        )

    # --- persistence (so the CLI can reuse a wallet across invocations) --
    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"privkey": hex(self.privkey), "address": self.address}))

    @staticmethod
    def load(path: Path) -> "Wallet":
        data = json.loads(path.read_text())
        return Wallet(privkey=int(data["privkey"], 16))
