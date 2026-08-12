"""UTXO-model transactions: inputs spend previous outputs by reference,
outputs create new spendable coins locked to an address. No account has a
"balance" field anywhere — a balance is a query over unspent outputs,
exactly like real Bitcoin.
"""

import struct

from ..crypto import secp256k1 as ec
from ..crypto.sha256 import sha256d
from ..crypto.base58 import b58check_decode

COINBASE_PREV_TXID = b"\x00" * 32
COINBASE_PREV_INDEX = 0xFFFFFFFF


def pubkey_to_address(pubkey_bytes: bytes) -> str:
    from ..crypto.base58 import b58check_encode
    pkh = sha256d(pubkey_bytes)[:20]  # "pubkey hash" (sha256d, not
    # ripemd160-of-sha256 like real Bitcoin, since ripemd160 isn't
    # reliably available in every stdlib build — same idea, own hash)
    return b58check_encode(b"\x00", pkh)


def address_to_pkh(address: str) -> bytes:
    version, pkh = b58check_decode(address)
    if version != b"\x00":
        raise ValueError("unsupported address version")
    return pkh


class TxIn:
    __slots__ = ("prev_txid", "prev_index", "pubkey", "signature")

    def __init__(self, prev_txid: bytes, prev_index: int, pubkey: bytes = b"", signature=None):
        self.prev_txid = prev_txid
        self.prev_index = prev_index
        self.pubkey = pubkey            # full pubkey bytes (compressed), empty until signed
        self.signature = signature      # (r, s) tuple, None until signed

    def is_coinbase(self) -> bool:
        return self.prev_txid == COINBASE_PREV_TXID and self.prev_index == COINBASE_PREV_INDEX

    def to_dict(self):
        return {
            "prev_txid": self.prev_txid.hex(),
            "prev_index": self.prev_index,
            "pubkey": self.pubkey.hex(),
            "signature": [self.signature[0], self.signature[1]] if self.signature else None,
        }

    @classmethod
    def from_dict(cls, d):
        sig = tuple(d["signature"]) if d["signature"] else None
        return cls(bytes.fromhex(d["prev_txid"]), d["prev_index"], bytes.fromhex(d["pubkey"]), sig)


class TxOut:
    __slots__ = ("amount", "to_address")

    def __init__(self, amount: int, to_address: str):
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self.amount = amount
        self.to_address = to_address

    def to_dict(self):
        return {"amount": self.amount, "to_address": self.to_address}

    @classmethod
    def from_dict(cls, d):
        return cls(d["amount"], d["to_address"])


class Transaction:
    __slots__ = ("inputs", "outputs")

    def __init__(self, inputs, outputs):
        self.inputs = inputs
        self.outputs = outputs

    def is_coinbase(self) -> bool:
        return len(self.inputs) == 1 and self.inputs[0].is_coinbase()

    def _signing_payload(self) -> bytes:
        """Serialization used both as the pre-image every input signs and
        as the txid pre-image. Signatures are NOT included here (that
        would be circular) — only prev outpoints, spender pubkeys, and
        all outputs are committed to. This is a simplification of
        Bitcoin's SIGHASH_ALL: every input authorizes the entire tx."""
        parts = [struct.pack(">I", len(self.inputs))]
        for txin in self.inputs:
            parts.append(txin.prev_txid)
            parts.append(struct.pack(">I", txin.prev_index))
            parts.append(struct.pack(">I", len(txin.pubkey)))
            parts.append(txin.pubkey)
        parts.append(struct.pack(">I", len(self.outputs)))
        for txout in self.outputs:
            parts.append(struct.pack(">Q", txout.amount))
            addr_bytes = txout.to_address.encode()
            parts.append(struct.pack(">I", len(addr_bytes)))
            parts.append(addr_bytes)
        return b"".join(parts)

    def sighash(self) -> bytes:
        return sha256d(self._signing_payload())

    def txid(self) -> bytes:
        """Deliberately uncached: a Transaction's inputs/outputs are plain
        mutable lists (needed so build_transaction/sign_input can assemble
        one incrementally), and caching txid() the first time it's called
        would silently go stale the moment anything mutates afterward —
        exactly the kind of bug that would defeat merkle-root tamper
        detection without ever raising an error. Recomputing is cheap at
        this project's scale; go straight to correct."""
        # include signatures in the txid so a mutated signature changes
        # the id (prevents trivial third-party malleability of the id)
        parts = [self._signing_payload()]
        for txin in self.inputs:
            if txin.signature:
                r, s = txin.signature
                parts.append(r.to_bytes(32, "big"))
                parts.append(s.to_bytes(32, "big"))
        return sha256d(b"".join(parts))

    def sign_input(self, index: int, privkey: int):
        pub = ec.privkey_to_pubkey(privkey)
        pub_bytes = ec.pubkey_to_bytes(pub, compressed=True)
        self.inputs[index].pubkey = pub_bytes
        sighash = self.sighash()
        self.inputs[index].signature = ec.sign(privkey, sighash)

    def verify_signatures(self) -> bool:
        """Structural signature check only (every input's signature is
        valid for its own pubkey over this tx's sighash). Does NOT check
        that the pubkey actually matches the UTXO being spent, or that the
        UTXO exists — that's Blockchain's job, since it needs chain state."""
        if self.is_coinbase():
            return True
        sighash = self.sighash()
        for txin in self.inputs:
            if not txin.pubkey or not txin.signature:
                return False
            try:
                pub = ec.bytes_to_pubkey(txin.pubkey)
            except (ValueError, IndexError):
                return False
            if not ec.verify(pub, sighash, txin.signature):
                return False
        return True

    def total_output(self) -> int:
        return sum(o.amount for o in self.outputs)

    def to_dict(self):
        return {
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
        }

    @classmethod
    def from_dict(cls, d):
        return cls([TxIn.from_dict(i) for i in d["inputs"]],
                    [TxOut.from_dict(o) for o in d["outputs"]])

    @staticmethod
    def coinbase(reward_address: str, amount: int, extra_nonce: int = 0):
        """A coinbase tx has no real input to spend — prev_txid is all
        zeros and prev_index is the sentinel 0xFFFFFFFF, matching Bitcoin.
        extra_nonce is folded into the (unused) pubkey field purely so two
        coinbases in a row can't collide on txid — same purpose as
        Bitcoin's coinbase scriptSig extra-nonce field."""
        txin = TxIn(COINBASE_PREV_TXID, COINBASE_PREV_INDEX,
                    pubkey=extra_nonce.to_bytes(8, "big"), signature=None)
        txout = TxOut(amount, reward_address)
        return Transaction([txin], [txout])
