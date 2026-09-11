"""UTXO transaction model: TxIn/TxOut/Transaction, Merkle trees, and the
Satoshi-style "blank all other inputs' scripts" signature hash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..crypto.hashes import double_sha256
from ..crypto import ecdsa
from ..crypto.address import parse_pubkey
from .script import Script

NULL_TXID = b"\x00" * 32
NULL_INDEX = 0xFFFFFFFF
SIGHASH_ALL = 0x01


def _write_varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    prefix = data[pos]
    if prefix < 0xFD:
        return prefix, pos + 1
    if prefix == 0xFD:
        return int.from_bytes(data[pos + 1:pos + 3], "little"), pos + 3
    if prefix == 0xFE:
        return int.from_bytes(data[pos + 1:pos + 5], "little"), pos + 5
    return int.from_bytes(data[pos + 1:pos + 9], "little"), pos + 9


@dataclass
class TxIn:
    prev_txid: bytes  # 32 bytes, NULL_TXID for a coinbase input
    prev_index: int
    script_sig: Script
    sequence: int = 0xFFFFFFFF

    def is_coinbase_input(self) -> bool:
        return self.prev_txid == NULL_TXID and self.prev_index == NULL_INDEX

    def serialize(self) -> bytes:
        sig = self.script_sig.serialize()
        return (
            self.prev_txid
            + self.prev_index.to_bytes(4, "little")
            + _write_varint(len(sig))
            + sig
            + self.sequence.to_bytes(4, "little")
        )

    @staticmethod
    def deserialize(data: bytes, pos: int) -> tuple["TxIn", int]:
        prev_txid = data[pos:pos + 32]
        pos += 32
        prev_index = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4
        slen, pos = _read_varint(data, pos)
        script_sig = Script.deserialize(data[pos:pos + slen])
        pos += slen
        sequence = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4
        return TxIn(prev_txid, prev_index, script_sig, sequence), pos


@dataclass
class TxOut:
    value: int  # integer "sats" (smallest unit)
    script_pubkey: Script

    def serialize(self) -> bytes:
        pk = self.script_pubkey.serialize()
        return self.value.to_bytes(8, "little") + _write_varint(len(pk)) + pk

    @staticmethod
    def deserialize(data: bytes, pos: int) -> tuple["TxOut", int]:
        value = int.from_bytes(data[pos:pos + 8], "little")
        pos += 8
        plen, pos = _read_varint(data, pos)
        script_pubkey = Script.deserialize(data[pos:pos + plen])
        pos += plen
        return TxOut(value, script_pubkey), pos


@dataclass
class Transaction:
    inputs: List[TxIn]
    outputs: List[TxOut]
    version: int = 1
    locktime: int = 0

    def is_coinbase(self) -> bool:
        return len(self.inputs) == 1 and self.inputs[0].is_coinbase_input()

    def serialize(self) -> bytes:
        out = bytearray()
        out += self.version.to_bytes(4, "little")
        out += _write_varint(len(self.inputs))
        for txin in self.inputs:
            out += txin.serialize()
        out += _write_varint(len(self.outputs))
        for txout in self.outputs:
            out += txout.serialize()
        out += self.locktime.to_bytes(4, "little")
        return bytes(out)

    @staticmethod
    def deserialize(data: bytes) -> "Transaction":
        pos = 0
        version = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4
        n_in, pos = _read_varint(data, pos)
        inputs = []
        for _ in range(n_in):
            txin, pos = TxIn.deserialize(data, pos)
            inputs.append(txin)
        n_out, pos = _read_varint(data, pos)
        outputs = []
        for _ in range(n_out):
            txout, pos = TxOut.deserialize(data, pos)
            outputs.append(txout)
        locktime = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4
        return Transaction(inputs, outputs, version, locktime)

    def txid(self) -> bytes:
        return double_sha256(self.serialize())

    def total_output_value(self) -> int:
        return sum(o.value for o in self.outputs)

    # -- signing -------------------------------------------------------

    def sighash(self, input_index: int, prevout_script: Script, sighash_type: int = SIGHASH_ALL) -> bytes:
        """The Satoshi-style legacy signature hash for one input.

        Every input's script_sig is blanked except `input_index`, whose
        script_sig is temporarily replaced with the *previous output's*
        locking script. This is what makes a signature bind to exactly
        which coin it authorizes spending, and to the whole transaction's
        outputs, without an input having to know any other input's
        unlocking data (which may not even be filled in yet).
        """
        if sighash_type != SIGHASH_ALL:
            raise ValueError("only SIGHASH_ALL is supported")
        stripped_inputs = []
        for i, txin in enumerate(self.inputs):
            script = prevout_script if i == input_index else Script([])
            stripped_inputs.append(TxIn(txin.prev_txid, txin.prev_index, script, txin.sequence))
        blanked = Transaction(stripped_inputs, self.outputs, self.version, self.locktime)
        return double_sha256(blanked.serialize() + sighash_type.to_bytes(4, "little"))

    def sign_input(self, input_index: int, privkey: int, prevout_script: Script, pubkey_bytes: bytes) -> None:
        sighash = self.sighash(input_index, prevout_script)
        sig = ecdsa.sign(privkey, sighash)
        der_with_type = sig.der_encode() + bytes([SIGHASH_ALL])
        self.inputs[input_index].script_sig = Script.p2pkh_unlock(der_with_type, pubkey_bytes)

    def make_sig_checker(self, input_index: int, prevout_script: Script):
        sighash = self.sighash(input_index, prevout_script)

        def checker(pubkey_bytes: bytes, sig_with_type: bytes) -> bool:
            if len(sig_with_type) < 2:
                return False
            sighash_type = sig_with_type[-1]
            if sighash_type != SIGHASH_ALL:
                return False
            try:
                pubkey = parse_pubkey(pubkey_bytes)
                sig = ecdsa.Signature.der_decode(sig_with_type[:-1])
            except (ValueError, IndexError):
                return False
            return ecdsa.verify(pubkey, sighash, sig)

        return checker


def merkle_root(txids: List[bytes]) -> bytes:
    """Bitcoin-style binary Merkle tree over a list of txids.

    An odd level duplicates its last element (the well-known CVE-2012-2459
    duplication quirk this repo won't silently ignore: see chain.py's
    handling, which additionally rejects blocks with an odd, non-trivial
    number of transactions with a duplicated tail pair, closing exactly
    that historical mutation vector).
    """
    if not txids:
        return b"\x00" * 32
    level = list(txids)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [double_sha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


@dataclass
class MerkleProof:
    leaf_index: int
    siblings: List[bytes]  # bottom-up

    def verify(self, leaf: bytes, root: bytes) -> bool:
        h = leaf
        idx = self.leaf_index
        for sib in self.siblings:
            h = double_sha256(h + sib) if idx % 2 == 0 else double_sha256(sib + h)
            idx //= 2
        return h == root


def merkle_proof(txids: List[bytes], leaf_index: int) -> MerkleProof:
    level = list(txids)
    idx = leaf_index
    siblings = []
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        pair_idx = idx ^ 1
        siblings.append(level[pair_idx])
        level = [double_sha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return MerkleProof(leaf_index, siblings)
