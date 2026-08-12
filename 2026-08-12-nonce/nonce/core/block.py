"""Block header + block, hashing, and the proof-of-work check itself."""

import struct
import time

from ..crypto.sha256 import sha256d
from .merkle import merkle_root
from .transaction import Transaction
from .difficulty import bits_to_target

VERSION = 1
GENESIS_PREV_HASH = b"\x00" * 32


class BlockHeader:
    __slots__ = ("version", "prev_hash", "merkle_root", "timestamp", "bits", "nonce", "_hash_cache")

    def __init__(self, version, prev_hash, merkle_root_, timestamp, bits, nonce):
        self.version = version
        self.prev_hash = prev_hash
        self.merkle_root = merkle_root_
        self.timestamp = timestamp
        self.bits = bits
        self.nonce = nonce
        self._hash_cache = None

    def serialize(self) -> bytes:
        return (struct.pack(">I", self.version) + self.prev_hash + self.merkle_root +
                struct.pack(">QII", self.timestamp, self.bits, self.nonce))

    def hash(self) -> bytes:
        if self._hash_cache is None:
            self._hash_cache = sha256d(self.serialize())
        return self._hash_cache

    def meets_target(self) -> bool:
        return int.from_bytes(self.hash(), "big") <= bits_to_target(self.bits)

    def to_dict(self):
        return {
            "version": self.version,
            "prev_hash": self.prev_hash.hex(),
            "merkle_root": self.merkle_root.hex(),
            "timestamp": self.timestamp,
            "bits": self.bits,
            "nonce": self.nonce,
            "hash": self.hash().hex(),
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d["version"], bytes.fromhex(d["prev_hash"]), bytes.fromhex(d["merkle_root"]),
                    d["timestamp"], d["bits"], d["nonce"])


class Block:
    __slots__ = ("header", "transactions", "height")

    def __init__(self, header: BlockHeader, transactions, height=None):
        self.header = header
        self.transactions = transactions
        self.height = height  # set once the block is connected to a chain

    def hash(self) -> bytes:
        return self.header.hash()

    def recompute_merkle_root(self):
        """Recompute header.merkle_root from self.transactions. Must be
        called (implicitly, via build_candidate below) any time the
        transaction set changes, before mining."""
        self.header.merkle_root = merkle_root([tx.txid() for tx in self.transactions])
        self.header._hash_cache = None

    def to_dict(self):
        return {
            "header": self.header.to_dict(),
            "transactions": [tx.to_dict() for tx in self.transactions],
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, d):
        header = BlockHeader.from_dict(d["header"])
        txs = [Transaction.from_dict(t) for t in d["transactions"]]
        return cls(header, txs, d.get("height"))


def build_candidate(prev_hash: bytes, bits: int, transactions, timestamp=None) -> Block:
    """Assemble an unmined block template (nonce=0) ready for a miner to
    grind. `transactions` must already include the coinbase as element 0."""
    header = BlockHeader(VERSION, prev_hash, b"\x00" * 32,
                          timestamp if timestamp is not None else int(time.time()), bits, 0)
    block = Block(header, list(transactions))
    block.recompute_merkle_root()
    return block


def genesis_block(coinbase_tx: Transaction, bits: int, timestamp: int) -> Block:
    block = build_candidate(GENESIS_PREV_HASH, bits, [coinbase_tx], timestamp)
    block.height = 0
    return block
