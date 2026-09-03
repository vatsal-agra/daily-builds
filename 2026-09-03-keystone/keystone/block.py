"""Block header + block: the unit the PoW search and chain validation both
operate on."""
from __future__ import annotations

from dataclasses import dataclass, field

from .crypto import sha256
from .merkle import merkle_root
from .serialize import canonical_bytes
from .transaction import Transaction


@dataclass
class BlockHeader:
    version: int
    prev_hash: str  # hex, 64 zeros for the genesis block
    merkle_root: str  # hex
    timestamp: float
    bits: int
    nonce: int = 0

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root,
            "timestamp": self.timestamp,
            "bits": self.bits,
            "nonce": self.nonce,
        }

    @staticmethod
    def from_dict(d: dict) -> "BlockHeader":
        return BlockHeader(d["version"], d["prev_hash"], d["merkle_root"], d["timestamp"], d["bits"], d["nonce"])

    def bytes_for_hash(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def hash(self) -> str:
        return sha256(sha256(self.bytes_for_hash())).hex()


@dataclass
class Block:
    header: BlockHeader
    transactions: list  # list[Transaction], transactions[0] is the coinbase
    height: int = 0  # informational only — not part of the hashed header

    def compute_merkle_root(self) -> str:
        leaf_hashes = [bytes.fromhex(tx.txid()) for tx in self.transactions]
        return merkle_root(leaf_hashes).hex()

    def hash(self) -> str:
        return self.header.hash()

    def to_dict(self) -> dict:
        return {
            "header": self.header.to_dict(),
            "transactions": [tx.to_dict() for tx in self.transactions],
            "height": self.height,
        }

    @staticmethod
    def from_dict(d: dict) -> "Block":
        return Block(
            header=BlockHeader.from_dict(d["header"]),
            transactions=[Transaction.from_dict(t) for t in d["transactions"]],
            height=d.get("height", 0),
        )


GENESIS_PREV_HASH = "0" * 64


def make_genesis_block(coinbase: Transaction, bits: int, timestamp: float = 0.0) -> Block:
    header = BlockHeader(
        version=1,
        prev_hash=GENESIS_PREV_HASH,
        merkle_root="",
        timestamp=timestamp,
        bits=bits,
        nonce=0,
    )
    block = Block(header=header, transactions=[coinbase], height=0)
    block.header.merkle_root = block.compute_merkle_root()
    return block
