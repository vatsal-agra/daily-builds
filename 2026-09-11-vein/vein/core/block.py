"""Block headers, proof-of-work target math, and block (de)serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..crypto.hashes import double_sha256
from .transaction import Transaction, merkle_root, _write_varint, _read_varint

MAX_TARGET = (1 << 256) - 1


def target_to_bits(target: int) -> int:
    """Encode a 256-bit target into Bitcoin's 4-byte compact ("nBits") form:
    1 exponent byte (target's size in bytes) + a 3-byte big-endian mantissa.
    Lossy by design (only ~24 significant bits survive) — real difficulty
    targets are compact on the wire for exactly this reason.
    """
    if target <= 0:
        return 0
    size = (target.bit_length() + 7) // 8
    if size <= 3:
        mantissa = target << (8 * (3 - size))
    else:
        mantissa = target >> (8 * (size - 3))
    if mantissa & 0x800000:  # top bit reserved as a sign bit; shift down
        mantissa >>= 8
        size += 1
    return (size << 24) | mantissa


def bits_to_target(bits: int) -> int:
    size = bits >> 24
    mantissa = bits & 0x7FFFFF
    if size <= 3:
        return mantissa >> (8 * (3 - size))
    return mantissa << (8 * (size - 3))


@dataclass
class BlockHeader:
    version: int
    prev_hash: bytes  # 32 bytes, all-zero for genesis
    merkle_root: bytes  # 32 bytes
    timestamp: int
    bits: int  # compact target encoding
    nonce: int = 0

    def serialize(self) -> bytes:
        return (
            self.version.to_bytes(4, "little")
            + self.prev_hash
            + self.merkle_root
            + self.timestamp.to_bytes(4, "little")
            + self.bits.to_bytes(4, "little")
            + self.nonce.to_bytes(4, "little")
        )

    @staticmethod
    def deserialize(data: bytes) -> "BlockHeader":
        assert len(data) == 80
        version = int.from_bytes(data[0:4], "little")
        prev_hash = data[4:36]
        merkle = data[36:68]
        timestamp = int.from_bytes(data[68:72], "little")
        bits = int.from_bytes(data[72:76], "little")
        nonce = int.from_bytes(data[76:80], "little")
        return BlockHeader(version, prev_hash, merkle, timestamp, bits, nonce)

    def hash(self) -> bytes:
        return double_sha256(self.serialize())

    def target(self) -> int:
        return bits_to_target(self.bits)

    def meets_target(self) -> bool:
        return int.from_bytes(self.hash(), "big") <= self.target()


@dataclass
class Block:
    header: BlockHeader
    transactions: List[Transaction] = field(default_factory=list)

    def hash(self) -> bytes:
        return self.header.hash()

    def compute_merkle_root(self) -> bytes:
        return merkle_root([tx.txid() for tx in self.transactions])

    def serialize(self) -> bytes:
        out = bytearray(self.header.serialize())
        out += _write_varint(len(self.transactions))
        for tx in self.transactions:
            raw = tx.serialize()
            out += _write_varint(len(raw))
            out += raw
        return bytes(out)

    @staticmethod
    def deserialize(data: bytes) -> "Block":
        header = BlockHeader.deserialize(data[:80])
        pos = 80
        n_tx, pos = _read_varint(data, pos)
        txs = []
        for _ in range(n_tx):
            tlen, pos = _read_varint(data, pos)
            txs.append(Transaction.deserialize(data[pos:pos + tlen]))
            pos += tlen
        return Block(header, txs)
