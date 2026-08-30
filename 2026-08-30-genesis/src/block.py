"""Block header, proof-of-work mining, and block (de)serialization.

Targets are kept as plain 256-bit integers rather than Bitcoin's packed
"compact bits" float-like encoding — compact-bits is a byte-saving trick
for the wire format, not part of the interesting protocol logic (that's
the retargeting math in `blockchain.py`), so we skip re-deriving it and
spend the effort on what the project is actually about.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from crypto import hash256
from merkle import merkle_root
from transaction import Transaction, _write_varint, _read_varint

# The easiest possible target (mining difficulty 1). Any lower target is harder.
MAX_TARGET = (1 << 256) - 1
NONCE_SPACE = 1 << 64


@dataclass
class BlockHeader:
    version: int
    prev_hash: bytes       # 32 bytes; all-zero for the genesis block
    merkle_root: bytes     # 32 bytes
    timestamp: int         # unix seconds
    target: int            # 256-bit PoW target; hash must be <= target
    nonce: int = 0

    def serialize(self) -> bytes:
        return (
            self.version.to_bytes(4, "big")
            + self.prev_hash
            + self.merkle_root
            + self.timestamp.to_bytes(8, "big")
            + self.target.to_bytes(32, "big")
            + self.nonce.to_bytes(8, "big")
        )

    @staticmethod
    def deserialize(buf: bytes, off: int = 0) -> Tuple["BlockHeader", int]:
        version = int.from_bytes(buf[off:off + 4], "big"); off += 4
        prev_hash = buf[off:off + 32]; off += 32
        mroot = buf[off:off + 32]; off += 32
        timestamp = int.from_bytes(buf[off:off + 8], "big"); off += 8
        target = int.from_bytes(buf[off:off + 32], "big"); off += 32
        nonce = int.from_bytes(buf[off:off + 8], "big"); off += 8
        return BlockHeader(version, prev_hash, mroot, timestamp, target, nonce), off

    def hash(self) -> bytes:
        return hash256(self.serialize())

    def meets_target(self) -> bool:
        return int.from_bytes(self.hash(), "big") <= self.target


@dataclass
class Block:
    header: BlockHeader
    transactions: List[Transaction] = field(default_factory=list)

    def block_hash(self) -> bytes:
        return self.header.hash()

    def block_hash_hex(self) -> str:
        return self.block_hash().hex()

    def compute_merkle_root(self) -> bytes:
        return merkle_root([t.txid() for t in self.transactions])

    def serialize(self) -> bytes:
        header_bytes = self.header.serialize()
        parts = [header_bytes, _write_varint(len(self.transactions))]
        for t in self.transactions:
            raw = t.serialize()
            parts.append(_write_varint(len(raw)) + raw)
        return b"".join(parts)

    @staticmethod
    def deserialize(buf: bytes, off: int = 0) -> Tuple["Block", int]:
        header, off = BlockHeader.deserialize(buf, off)
        n_tx, off = _read_varint(buf, off)
        txs = []
        for _ in range(n_tx):
            tlen, off = _read_varint(buf, off)
            raw = buf[off:off + tlen]
            t, _ = Transaction.deserialize(raw)
            txs.append(t)
            off += tlen
        return Block(header, txs), off

    @staticmethod
    def new(prev_hash: bytes, transactions: List[Transaction], target: int,
            timestamp: Optional[int] = None, version: int = 1) -> "Block":
        b = Block(header=BlockHeader(
            version=version, prev_hash=prev_hash, merkle_root=b"\x00" * 32,
            timestamp=timestamp if timestamp is not None else int(time.time()),
            target=target, nonce=0,
        ), transactions=transactions)
        b.header.merkle_root = b.compute_merkle_root()
        return b

    def mine(self, max_nonce: int = NONCE_SPACE, nonce_start: int = 0) -> Optional[int]:
        """Search nonces until the header hash meets the target.
        Returns the winning nonce, or None if max_nonce is exhausted
        (caller should then bump the timestamp/extra-nonce and retry —
        exactly what real miners do when they exhaust the nonce space)."""
        self.header.merkle_root = self.compute_merkle_root()
        nonce = nonce_start
        while nonce < max_nonce:
            self.header.nonce = nonce
            if self.header.meets_target():
                return nonce
            nonce += 1
        return None

    def is_valid_pow(self) -> bool:
        return self.header.meets_target()
