"""UTXO transaction model: inputs spend prior outputs, outputs create new ones.

Serialization is canonical JSON (sorted keys, compact separators) — a
deliberate choice over a hand-rolled binary format so the wire protocol,
the hashing input, and what you'd see in a debugger/log are all the exact
same bytes, which matters a lot when every prior "from scratch" project in
this repo already proved the value of a hand-rolled binary codec (Graft,
Kiln, Silicon). Here the interesting bytes are the *signature* math, not
the framing.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import ecdsa
from .crypto import hash160, pubkey_to_address, sha256d

COINBASE_PREV_TXID = "0" * 64
COINBASE_PREV_INDEX = -1


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class TxIn:
    prev_txid: str
    prev_index: int
    pubkey: Optional[str] = None       # hex-encoded compressed pubkey (None for coinbase)
    signature: Optional[str] = None    # hex-encoded DER signature (None for coinbase/unsigned)

    def to_dict(self) -> dict:
        return {
            "prev_txid": self.prev_txid,
            "prev_index": self.prev_index,
            "pubkey": self.pubkey,
            "signature": self.signature,
        }

    @staticmethod
    def from_dict(d: dict) -> "TxIn":
        return TxIn(d["prev_txid"], d["prev_index"], d.get("pubkey"), d.get("signature"))

    @property
    def is_coinbase(self) -> bool:
        return self.prev_txid == COINBASE_PREV_TXID and self.prev_index == COINBASE_PREV_INDEX


@dataclass
class TxOut:
    address: str
    amount: int  # integer "coin" units — never float, to keep sums exact

    def to_dict(self) -> dict:
        return {"address": self.address, "amount": self.amount}

    @staticmethod
    def from_dict(d: dict) -> "TxOut":
        return TxOut(d["address"], int(d["amount"]))


@dataclass
class Transaction:
    inputs: List[TxIn]
    outputs: List[TxOut]
    timestamp: float = field(default_factory=time.time)
    coinbase_data: Optional[str] = None  # height+nonce string, keeps coinbase txid unique
    version: int = 1

    # --- serialization -----------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "coinbase_data": self.coinbase_data,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
        }

    @staticmethod
    def from_dict(d: dict) -> "Transaction":
        return Transaction(
            inputs=[TxIn.from_dict(i) for i in d["inputs"]],
            outputs=[TxOut.from_dict(o) for o in d["outputs"]],
            timestamp=d["timestamp"],
            coinbase_data=d.get("coinbase_data"),
            version=d.get("version", 1),
        )

    def _signing_payload(self) -> bytes:
        """What every input signature covers: everything except signatures."""
        stripped_inputs = [
            {"prev_txid": i.prev_txid, "prev_index": i.prev_index, "pubkey": i.pubkey}
            for i in self.inputs
        ]
        payload = {
            "version": self.version,
            "timestamp": self.timestamp,
            "coinbase_data": self.coinbase_data,
            "inputs": stripped_inputs,
            "outputs": [o.to_dict() for o in self.outputs],
        }
        return _canonical(payload)

    def sighash(self) -> bytes:
        return sha256d(self._signing_payload())

    def txid(self) -> str:
        return sha256d(_canonical(self.to_dict())).hex()

    @property
    def is_coinbase(self) -> bool:
        return len(self.inputs) == 1 and self.inputs[0].is_coinbase

    def total_output(self) -> int:
        return sum(o.amount for o in self.outputs)

    # --- signing / verification ---------------------------------------
    def sign_input(self, index: int, privkey: int) -> None:
        txin = self.inputs[index]
        pub = ecdsa.private_to_public(privkey)
        txin.pubkey = ecdsa.compress_pubkey(pub).hex()
        digest = self.sighash()
        sig = ecdsa.sign(digest, privkey)
        txin.signature = sig.to_der().hex()

    def verify_signatures(self) -> Tuple[bool, str]:
        """Structural signature check only — does NOT check UTXO ownership
        or double-spends; see chain.validate_transaction for full checks."""
        if self.is_coinbase:
            return True, ""
        if not self.inputs:
            return False, "transaction has no inputs"
        digest = self.sighash()
        for idx, txin in enumerate(self.inputs):
            if not txin.pubkey or not txin.signature:
                return False, f"input {idx} is missing pubkey/signature"
            try:
                pub = ecdsa.decompress_pubkey(bytes.fromhex(txin.pubkey))
                sig = ecdsa.Signature.from_der(bytes.fromhex(txin.signature))
            except (ValueError, IndexError) as exc:
                return False, f"input {idx} malformed pubkey/signature: {exc}"
            if not ecdsa.verify(digest, sig, pub):
                return False, f"input {idx} signature does not verify"
        return True, ""


def make_coinbase(reward_address: str, amount: int, height: int, extra_nonce: int = 0) -> Transaction:
    tx = Transaction(
        inputs=[TxIn(COINBASE_PREV_TXID, COINBASE_PREV_INDEX)],
        outputs=[TxOut(reward_address, amount)],
        coinbase_data=f"height={height};nonce={extra_nonce}",
    )
    return tx


def build_transaction(
    utxos: List[Tuple[str, int, int]],  # (prev_txid, prev_index, amount) being spent
    privkey: int,
    to_address: str,
    amount: int,
    fee: int,
    change_address: str,
) -> Transaction:
    """Construct + sign a simple single-key transaction spending `utxos`."""
    total_in = sum(u[2] for u in utxos)
    if total_in < amount + fee:
        raise ValueError(f"insufficient funds: have {total_in}, need {amount + fee}")
    inputs = [TxIn(txid, idx) for txid, idx, _amt in utxos]
    outputs = [TxOut(to_address, amount)]
    change = total_in - amount - fee
    if change > 0:
        outputs.append(TxOut(change_address, change))
    tx = Transaction(inputs=inputs, outputs=outputs)
    for i in range(len(tx.inputs)):
        tx.sign_input(i, privkey)
    return tx
