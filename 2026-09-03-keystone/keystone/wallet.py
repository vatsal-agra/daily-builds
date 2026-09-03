"""Wallets: a secp256k1 keypair plus address derivation and a helper to
build+sign a spending transaction from a set of owned UTXOs."""
from __future__ import annotations

from dataclasses import dataclass

from . import crypto, script
from .transaction import Transaction, TxIn, TxOut

ADDRESS_VERSION = 0x00


@dataclass
class Wallet:
    privkey: int
    pubkey: tuple  # (x, y) point

    @staticmethod
    def generate() -> "Wallet":
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        return Wallet(priv, pub)

    @staticmethod
    def from_privkey(privkey: int) -> "Wallet":
        return Wallet(privkey, crypto.private_to_public(privkey))

    @property
    def pubkey_compressed(self) -> bytes:
        return crypto.compress_pubkey(self.pubkey)

    @property
    def pubkey_hash(self) -> bytes:
        return crypto.hash160(self.pubkey_compressed)

    @property
    def address(self) -> str:
        return crypto.b58check_encode(self.pubkey_hash, version=ADDRESS_VERSION)

    @staticmethod
    def address_to_pubkey_hash(address: str) -> bytes:
        version, payload = crypto.b58check_decode(address)
        if version != ADDRESS_VERSION:
            raise ValueError(f"unexpected address version {version}")
        return payload

    def lock_script_for_self(self) -> list:
        return script.p2pkh_lock(self.pubkey_hash)

    def build_transaction(self, inputs: list, outputs: list) -> Transaction:
        """inputs: list of (prev_txid, prev_index) UTXOs this wallet owns
        and is spending (all assumed to be P2PKH-locked to this wallet's
        own key — spending someone else's UTXO or a multisig one needs its
        own unlocking script built by the caller, not this convenience
        helper). outputs: list of (amount, recipient_pubkey_hash)."""
        txins = [TxIn(prev_txid=txid, prev_index=idx, script_sig=[]) for txid, idx in inputs]
        txouts = [TxOut(amount=amt, script_pubkey=script.p2pkh_lock(pkh)) for amt, pkh in outputs]
        tx = Transaction(inputs=txins, outputs=txouts)
        sighash = tx.signing_hash()
        for txin in tx.inputs:
            txin.script_sig = script.p2pkh_unlock(self.privkey, sighash, self.pubkey_compressed)
        return tx
