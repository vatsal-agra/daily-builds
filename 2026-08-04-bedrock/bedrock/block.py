"""Block header + block body, canonical serialization, and block hashing."""

from dataclasses import dataclass, field

from bedrock import binfmt
from bedrock.crypto import sha256d
from bedrock.merkle import merkle_root
from bedrock.transaction import Transaction

GENESIS_PREV_HASH = "00" * 32


class BlockError(ValueError):
    pass


@dataclass
class BlockHeader:
    version: int
    prev_hash: str      # hex, 64 chars
    merkle_root: str    # hex, 64 chars
    timestamp: int       # unix seconds
    target: int          # 256-bit integer PoW target (hash must be < target)
    nonce: int = 0

    def to_bytes(self) -> bytes:
        prev = bytes.fromhex(self.prev_hash)
        root = bytes.fromhex(self.merkle_root)
        if len(prev) != 32 or len(root) != 32:
            raise BlockError("prev_hash/merkle_root must be 32-byte hex strings")
        out = binfmt.write_varint(self.version)
        out += prev
        out += root
        out += binfmt.write_varint(self.timestamp)
        out += self.target.to_bytes(32, "big")
        out += binfmt.write_varint(self.nonce)
        return out

    @staticmethod
    def from_bytes(buf: bytes, offset: int = 0):
        version, offset = binfmt.read_varint(buf, offset)
        prev_hash = buf[offset:offset + 32].hex(); offset += 32
        root = buf[offset:offset + 32].hex(); offset += 32
        timestamp, offset = binfmt.read_varint(buf, offset)
        target = int.from_bytes(buf[offset:offset + 32], "big"); offset += 32
        nonce, offset = binfmt.read_varint(buf, offset)
        return BlockHeader(version, prev_hash, root, timestamp, target, nonce), offset

    @property
    def hash(self) -> str:
        return sha256d(self.to_bytes()).hex()


@dataclass
class Block:
    header: BlockHeader
    transactions: list = field(default_factory=list)

    @property
    def hash(self) -> str:
        return self.header.hash

    def compute_merkle_root(self) -> str:
        leaves = [bytes.fromhex(tx.txid) for tx in self.transactions]
        return merkle_root(leaves).hex()

    def to_bytes(self) -> bytes:
        out = self.header.to_bytes()
        out += binfmt.write_varint(len(self.transactions))
        for tx in self.transactions:
            out += binfmt.write_bytes(tx.to_bytes())
        return out

    @staticmethod
    def from_bytes(buf: bytes, offset: int = 0):
        header, offset = BlockHeader.from_bytes(buf, offset)
        n_tx, offset = binfmt.read_varint(buf, offset)
        txs = []
        for _ in range(n_tx):
            tx_bytes, offset = binfmt.read_bytes(buf, offset)
            tx, _ = Transaction.from_bytes(tx_bytes)
            txs.append(tx)
        return Block(header, txs), offset

    def to_dict(self) -> dict:
        """JSON-friendly view for the network layer / explorer (not used for
        hashing — the canonical hash always comes from to_bytes())."""
        return {
            "hash": self.hash,
            "version": self.header.version,
            "prev_hash": self.header.prev_hash,
            "merkle_root": self.header.merkle_root,
            "timestamp": self.header.timestamp,
            "target": hex(self.header.target),
            "nonce": self.header.nonce,
            "raw": self.to_bytes().hex(),
        }

    @staticmethod
    def from_wire_hex(raw_hex: str) -> "Block":
        block, _ = Block.from_bytes(bytes.fromhex(raw_hex))
        return block
