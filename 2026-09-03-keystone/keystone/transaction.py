"""UTXO transactions: inputs spend prior outputs by reference + an unlocking
script; outputs carry an amount and a locking script (see script.py)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .crypto import double_sha256
from .serialize import canonical_bytes

COINBASE_PREV_TXID = "0" * 64
COINBASE_PREV_INDEX = -1


@dataclass
class TxIn:
    prev_txid: str
    prev_index: int
    script_sig: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prev_txid": self.prev_txid,
            "prev_index": self.prev_index,
            "script_sig": self.script_sig,
        }

    @staticmethod
    def from_dict(d: dict) -> "TxIn":
        return TxIn(d["prev_txid"], d["prev_index"], list(d.get("script_sig", [])))

    @property
    def outpoint(self):
        return (self.prev_txid, self.prev_index)

    @property
    def is_coinbase(self) -> bool:
        return self.prev_txid == COINBASE_PREV_TXID and self.prev_index == COINBASE_PREV_INDEX


@dataclass
class TxOut:
    amount: int  # integer smallest-unit "keys" (no floats anywhere in the ledger)
    script_pubkey: list

    def to_dict(self) -> dict:
        return {"amount": self.amount, "script_pubkey": self.script_pubkey}

    @staticmethod
    def from_dict(d: dict) -> "TxOut":
        return TxOut(int(d["amount"]), list(d["script_pubkey"]))


@dataclass
class Transaction:
    inputs: list
    outputs: list
    version: int = 1
    locktime: int = 0

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "locktime": self.locktime,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
        }

    @staticmethod
    def from_dict(d: dict) -> "Transaction":
        return Transaction(
            inputs=[TxIn.from_dict(i) for i in d["inputs"]],
            outputs=[TxOut.from_dict(o) for o in d["outputs"]],
            version=d.get("version", 1),
            locktime=d.get("locktime", 0),
        )

    def signing_hash(self) -> bytes:
        """The digest every input's unlocking-script signature is taken
        over: commits to every prevout referenced and every output paid,
        so neither can be tampered with after signing (a SIGHASH_ALL
        equivalent) — but deliberately *not* to the script_sig contents
        themselves, since that's the very thing being produced."""
        body = {
            "version": self.version,
            "locktime": self.locktime,
            "inputs": [{"prev_txid": i.prev_txid, "prev_index": i.prev_index} for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
        }
        return double_sha256(canonical_bytes(body))

    def txid(self) -> str:
        return double_sha256(canonical_bytes(self.to_dict())).hex()

    @property
    def is_coinbase(self) -> bool:
        return len(self.inputs) == 1 and self.inputs[0].is_coinbase

    def total_output(self) -> int:
        return sum(o.amount for o in self.outputs)


def make_coinbase(reward_script_pubkey: list, amount: int, height: int, extra_nonce: int) -> Transaction:
    """A coinbase transaction has no real input to spend; `height` and
    `extra_nonce` are embedded in script_sig purely so two coinbase
    transactions (e.g. from two miners racing for the same reward amount at
    the same height) never accidentally serialize identically and collide
    on txid — the exact real-world failure Bitcoin hit and fixed with
    BIP34 (mandatory height-in-coinbase)."""
    txin = TxIn(
        prev_txid=COINBASE_PREV_TXID,
        prev_index=COINBASE_PREV_INDEX,
        script_sig=[f"height:{height}", f"extra_nonce:{extra_nonce}"],
    )
    txout = TxOut(amount=amount, script_pubkey=reward_script_pubkey)
    return Transaction(inputs=[txin], outputs=[txout])
