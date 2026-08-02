"""UTXO-model transactions.

Every non-coinbase input names the (txid, output_index) it spends and
carries the spender's compressed public key plus an ECDSA signature over
the transaction's signing payload (inputs' outpoints + all outputs, with
signatures themselves excluded so signing is well-defined). Ownership is
checked at validation time (chain.py) by hashing the supplied pubkey and
confirming it matches the address the referenced UTXO actually pays to —
a forged pubkey that doesn't hash to the right address is rejected even
if it signs correctly over its own key.
"""

import json

from . import curve
from .merkle import sha256d

COINBASE_TXID = "0" * 64


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


class TxInput:
    __slots__ = ("txid", "index", "pubkey", "signature")

    def __init__(self, txid, index, pubkey=None, signature=None):
        self.txid = txid
        self.index = index
        self.pubkey = pubkey        # bytes (compressed pubkey) or None for coinbase
        self.signature = signature  # bytes (64) or None

    @property
    def is_coinbase(self):
        return self.txid == COINBASE_TXID and self.index == -1

    def to_dict(self, include_signature=True):
        d = {
            "txid": self.txid,
            "index": self.index,
            "pubkey": self.pubkey.hex() if self.pubkey else None,
        }
        if include_signature:
            d["signature"] = self.signature.hex() if self.signature else None
        return d

    @staticmethod
    def from_dict(d):
        return TxInput(
            d["txid"],
            d["index"],
            bytes.fromhex(d["pubkey"]) if d.get("pubkey") else None,
            bytes.fromhex(d["signature"]) if d.get("signature") else None,
        )


class TxOutput:
    __slots__ = ("amount", "address")

    def __init__(self, amount, address):
        if amount < 0:
            raise ValueError("output amount cannot be negative")
        self.amount = amount
        self.address = address

    def to_dict(self):
        return {"amount": self.amount, "address": self.address}

    @staticmethod
    def from_dict(d):
        return TxOutput(d["amount"], d["address"])


class Transaction:
    def __init__(self, inputs, outputs, coinbase_data=None):
        self.inputs = inputs
        self.outputs = outputs
        # extra entropy so two coinbase txs (same miner, same reward) never collide
        self.coinbase_data = coinbase_data

    @property
    def is_coinbase(self):
        return len(self.inputs) == 1 and self.inputs[0].is_coinbase

    def signing_payload(self, input_index):
        """The bytes a given input's signature is computed over: the full
        set of outpoints being spent (txid+index+pubkey, no signatures)
        plus all outputs. Binding every input to every other input's
        outpoint prevents an attacker from splicing this signed input
        into a transaction with different, unsigned outputs."""
        payload = {
            "inputs": [inp.to_dict(include_signature=False) for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
            "signer_index": input_index,
        }
        return _canonical(payload)

    def sign_input(self, index, private_key):
        inp = self.inputs[index]
        msg = self.signing_payload(index)
        r, s = curve.sign(private_key, msg)
        inp.signature = curve.sig_to_bytes((r, s))

    def verify_input_signature(self, index):
        """Verifies only that the signature was made by the holder of the
        stated pubkey — NOT that the pubkey is entitled to the UTXO being
        spent. That ownership check needs the UTXO set and lives in chain.py."""
        inp = self.inputs[index]
        if inp.pubkey is None or inp.signature is None:
            return False
        try:
            point = curve.decompress_pubkey(inp.pubkey)
            sig = curve.sig_from_bytes(inp.signature)
        except ValueError:
            return False
        return curve.verify(point, self.signing_payload(index), sig)

    def to_dict(self):
        d = {
            "inputs": [inp.to_dict() for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
        }
        if self.coinbase_data is not None:
            d["coinbase_data"] = self.coinbase_data
        return d

    @staticmethod
    def from_dict(d):
        return Transaction(
            [TxInput.from_dict(i) for i in d["inputs"]],
            [TxOutput.from_dict(o) for o in d["outputs"]],
            coinbase_data=d.get("coinbase_data"),
        )

    def txid(self) -> str:
        return sha256d(_canonical(self.to_dict())).hex()

    def total_output(self) -> int:
        return sum(o.amount for o in self.outputs)

    @staticmethod
    def new_coinbase(reward_address, amount, height, extra=""):
        inp = TxInput(COINBASE_TXID, -1, pubkey=None, signature=None)
        out = TxOutput(amount, reward_address)
        return Transaction([inp], [out], coinbase_data=f"height={height};{extra}")
