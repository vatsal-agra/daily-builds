"""A wallet: a keypair plus convenience methods to check balance and
build signed transactions against a blockchain's UTXO set."""

import secrets

from .crypto import secp256k1 as ec
from .core.transaction import Transaction, TxIn, TxOut, pubkey_to_address, address_to_pkh


class InsufficientFunds(Exception):
    pass


class Wallet:
    def __init__(self, privkey: int = None):
        self.privkey = privkey if privkey is not None else (secrets.randbelow(ec.N - 1) + 1)
        self.pubkey = ec.privkey_to_pubkey(self.privkey)
        self.pubkey_bytes = ec.pubkey_to_bytes(self.pubkey, compressed=True)
        self.address = pubkey_to_address(self.pubkey_bytes)

    def balance(self, blockchain) -> int:
        return blockchain.balance(self.address)

    def build_transaction(self, blockchain, to_address: str, amount: int, fee: int = 0,
                           extra_utxos: dict = None) -> Transaction:
        """Selects UTXOs owned by this wallet from `blockchain` (plus any
        already-known unconfirmed change/outputs passed via extra_utxos,
        keyed the same way as blockchain.utxo_set) to cover amount+fee,
        signs every input, and returns the finished transaction. Any
        leftover is sent back to this wallet as a change output."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        try:
            address_to_pkh(to_address)
        except (ValueError, IndexError) as e:
            # Fail loudly and *before* mining, not silently: TxOut never
            # checks its own to_address, so without this a typo'd or
            # garbage destination would mine successfully and just burn
            # the funds forever, with the sender none the wiser.
            raise ValueError(f"{to_address!r} is not a valid Nonce address: {e}") from None
        available = blockchain.utxos_for(self.address)
        if extra_utxos:
            available = {**available, **{k: v for k, v in extra_utxos.items() if v.to_address == self.address}}

        need = amount + fee
        selected = []
        total = 0
        # simplest-possible coin selection: largest-first (keeps input
        # counts, and thus the demo's tx graph, easy to follow)
        for key, txout in sorted(available.items(), key=lambda kv: -kv[1].amount):
            selected.append(key)
            total += txout.amount
            if total >= need:
                break
        if total < need:
            raise InsufficientFunds(f"{self.address} has {total}, needs {need}")

        inputs = [TxIn(txid, index) for (txid, index) in selected]
        outputs = [TxOut(amount, to_address)]
        change = total - need
        if change > 0:
            outputs.append(TxOut(change, self.address))

        tx = Transaction(inputs, outputs)
        for i in range(len(inputs)):
            tx.sign_input(i, self.privkey)
        return tx

    def __repr__(self):
        return f"Wallet(address={self.address})"
