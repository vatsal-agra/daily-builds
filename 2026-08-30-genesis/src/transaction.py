"""Transactions: the UTXO model, from-scratch ECDSA authorization.

A transaction spends previously-unspent outputs (UTXOs) and creates new
ones. Each non-coinbase input must carry the spender's public key and a
secp256k1 signature over a hash that commits to every input's referenced
outpoint + spending pubkey and every output's amount + destination — so
mutating anything about the transaction after signing invalidates every
signature on it.

Serialization is a small hand-rolled deterministic binary format (varints
+ fixed-width fields), not JSON/pickle — the same content always produces
the same bytes, which is required since bytes are what gets hashed for
both the signature preimage and the transaction id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from crypto import hash256, sign as ecdsa_sign, verify as ecdsa_verify, hash160, decompress_pubkey

COINBASE_PREV_TXID = b"\x00" * 32
COINBASE_PREV_INDEX = 0xFFFFFFFF


def _write_varint(n: int) -> bytes:
    if n < 0xFD:
        return n.to_bytes(1, "big")
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "big")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "big")
    return b"\xff" + n.to_bytes(8, "big")


def _read_varint(buf: bytes, off: int) -> Tuple[int, int]:
    tag = buf[off]
    if tag < 0xFD:
        return tag, off + 1
    if tag == 0xFD:
        return int.from_bytes(buf[off + 1:off + 3], "big"), off + 3
    if tag == 0xFE:
        return int.from_bytes(buf[off + 1:off + 5], "big"), off + 5
    return int.from_bytes(buf[off + 1:off + 9], "big"), off + 9


@dataclass
class TxOut:
    amount: int          # smallest unit ("sats"), must be a non-negative int
    pubkey_hash: bytes   # 20-byte hash160 of the recipient's public key

    def serialize(self) -> bytes:
        return self.amount.to_bytes(8, "big") + self.pubkey_hash

    @staticmethod
    def deserialize(buf: bytes, off: int) -> Tuple["TxOut", int]:
        amount = int.from_bytes(buf[off:off + 8], "big")
        pkh = buf[off + 8:off + 28]
        return TxOut(amount, pkh), off + 28


@dataclass
class TxIn:
    prev_txid: bytes
    prev_index: int
    pubkey: bytes = b""                       # spender's compressed pubkey (33 bytes), b"" for coinbase
    signature: Optional[Tuple[int, int]] = None
    coinbase_data: bytes = b""                # only meaningful when this is a coinbase input

    def is_coinbase(self) -> bool:
        return self.prev_txid == COINBASE_PREV_TXID and self.prev_index == COINBASE_PREV_INDEX

    def _prevout_ref_bytes(self) -> bytes:
        """The part of an input that goes into the signature preimage."""
        if self.is_coinbase():
            return self.prev_txid + self.prev_index.to_bytes(4, "big") + \
                _write_varint(len(self.coinbase_data)) + self.coinbase_data
        return self.prev_txid + self.prev_index.to_bytes(4, "big") + self.pubkey

    def serialize(self) -> bytes:
        sig_bytes = b""
        if self.signature is not None:
            r, s = self.signature
            sig_bytes = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return (
            self._prevout_ref_bytes()
            + _write_varint(len(sig_bytes)) + sig_bytes
        )

    @staticmethod
    def deserialize(buf: bytes, off: int) -> Tuple["TxIn", int]:
        prev_txid = buf[off:off + 32]
        prev_index = int.from_bytes(buf[off + 32:off + 36], "big")
        off2 = off + 36
        if prev_txid == COINBASE_PREV_TXID and prev_index == COINBASE_PREV_INDEX:
            cb_len, off2 = _read_varint(buf, off2)
            coinbase_data = buf[off2:off2 + cb_len]
            off2 += cb_len
            sig_len, off2 = _read_varint(buf, off2)
            off2 += sig_len  # always 0 for coinbase
            return TxIn(prev_txid, prev_index, b"", None, coinbase_data), off2
        pubkey = buf[off2:off2 + 33]
        off2 += 33
        sig_len, off2 = _read_varint(buf, off2)
        sig = None
        if sig_len:
            r = int.from_bytes(buf[off2:off2 + 32], "big")
            s = int.from_bytes(buf[off2 + 32:off2 + 64], "big")
            sig = (r, s)
        off2 += sig_len
        return TxIn(prev_txid, prev_index, pubkey, sig, b""), off2


@dataclass
class Transaction:
    inputs: List[TxIn] = field(default_factory=list)
    outputs: List[TxOut] = field(default_factory=list)
    version: int = 1
    lock_time: int = 0

    # -- signing -------------------------------------------------------
    def sighash(self) -> bytes:
        """Hash committing to every input's outpoint+pubkey and every output.
        Signing this (once per input, with that input's own key) means any
        change to any input or output after signing invalidates every
        signature on the transaction."""
        parts = [self.version.to_bytes(4, "big"), _write_varint(len(self.inputs))]
        for txin in self.inputs:
            parts.append(txin._prevout_ref_bytes())
        parts.append(_write_varint(len(self.outputs)))
        for txout in self.outputs:
            parts.append(txout.serialize())
        parts.append(self.lock_time.to_bytes(4, "big"))
        return hash256(b"".join(parts))

    def sign_input(self, index: int, private_key: int) -> None:
        txin = self.inputs[index]
        if txin.is_coinbase():
            raise ValueError("cannot sign a coinbase input")
        h = self.sighash()
        txin.signature = ecdsa_sign(h, private_key)

    def verify(self, utxo_lookup) -> Tuple[bool, str]:
        """Verify every non-coinbase input's signature and that its pubkey
        matches the referenced UTXO's locking pubkey_hash.

        `utxo_lookup(txid, index) -> Optional[TxOut]` resolves a prevout;
        callers (Blockchain/Mempool) are responsible for the *set*-level
        checks (output actually unspent, no double-spend within the same
        block) since those require chain state this function doesn't have.
        """
        if not self.inputs:
            return False, "transaction has no inputs"
        if not self.outputs:
            return False, "transaction has no outputs"
        for txout in self.outputs:
            if txout.amount < 0:
                return False, "negative output amount"
        seen_outpoints = set()
        for txin in self.inputs:
            key = (txin.prev_txid, txin.prev_index)
            if key in seen_outpoints and not txin.is_coinbase():
                return False, "same output referenced by two inputs in one transaction"
            seen_outpoints.add(key)
        h = self.sighash()
        total_in = 0
        for i, txin in enumerate(self.inputs):
            if txin.is_coinbase():
                if len(self.inputs) != 1:
                    return False, "coinbase must be the sole input"
                continue
            prevout = utxo_lookup(txin.prev_txid, txin.prev_index)
            if prevout is None:
                return False, f"input {i} references a missing/spent output"
            if hash160(txin.pubkey) != prevout.pubkey_hash:
                return False, f"input {i} pubkey does not match output's locking hash"
            if txin.signature is None:
                return False, f"input {i} is unsigned"
            try:
                pub_point = decompress_pubkey(txin.pubkey)
            except ValueError:
                return False, f"input {i} has an invalid public key"
            if not ecdsa_verify(h, txin.signature, pub_point):
                return False, f"input {i} signature does not verify"
            total_in += prevout.amount
        if not self.is_coinbase() and total_in < self.total_output():
            return False, "inputs do not cover outputs (would create value from nothing)"
        return True, "ok"

    def fee(self, utxo_lookup) -> int:
        """Sum(input amounts) - sum(output amounts). Caller must have already
        verified the transaction; behavior on an unverified/invalid tx is
        undefined (may raise or return a nonsense value)."""
        if self.is_coinbase():
            return 0
        total_in = sum(utxo_lookup(i.prev_txid, i.prev_index).amount for i in self.inputs)
        return total_in - self.total_output()

    def is_coinbase(self) -> bool:
        return len(self.inputs) == 1 and self.inputs[0].is_coinbase()

    def total_output(self) -> int:
        return sum(o.amount for o in self.outputs)

    # -- (de)serialization / id -----------------------------------------
    def serialize(self) -> bytes:
        parts = [self.version.to_bytes(4, "big"), _write_varint(len(self.inputs))]
        for txin in self.inputs:
            parts.append(txin.serialize())
        parts.append(_write_varint(len(self.outputs)))
        for txout in self.outputs:
            parts.append(txout.serialize())
        parts.append(self.lock_time.to_bytes(4, "big"))
        return b"".join(parts)

    @staticmethod
    def deserialize(buf: bytes, off: int = 0) -> Tuple["Transaction", int]:
        version = int.from_bytes(buf[off:off + 4], "big")
        off += 4
        n_in, off = _read_varint(buf, off)
        inputs = []
        for _ in range(n_in):
            txin, off = TxIn.deserialize(buf, off)
            inputs.append(txin)
        n_out, off = _read_varint(buf, off)
        outputs = []
        for _ in range(n_out):
            txout, off = TxOut.deserialize(buf, off)
            outputs.append(txout)
        lock_time = int.from_bytes(buf[off:off + 4], "big")
        off += 4
        return Transaction(inputs, outputs, version, lock_time), off

    def txid(self) -> bytes:
        return hash256(self.serialize())

    def txid_hex(self) -> str:
        return self.txid().hex()

    @staticmethod
    def coinbase(pubkey_hash: bytes, reward: int, height: int, extra: bytes = b"") -> "Transaction":
        txin = TxIn(
            prev_txid=COINBASE_PREV_TXID,
            prev_index=COINBASE_PREV_INDEX,
            coinbase_data=height.to_bytes(4, "big") + extra,
        )
        txout = TxOut(amount=reward, pubkey_hash=pubkey_hash)
        return Transaction(inputs=[txin], outputs=[txout])
