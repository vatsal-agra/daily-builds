import json
import time

from .merkle import merkle_root, sha256d
from .transaction import Transaction

GENESIS_PREV_HASH = "0" * 64


class Block:
    def __init__(self, height, prev_hash, transactions, target, timestamp=None, nonce=0):
        self.height = height
        self.prev_hash = prev_hash
        self.transactions = transactions  # list[Transaction]
        self.target = target
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.nonce = nonce
        self._merkle_root_hex = None  # cached: nonce search re-hashes the header
                                       # every attempt, but the tx set (and thus
                                       # the merkle root) never changes during mining

    @property
    def merkle_root_hex(self):
        if self._merkle_root_hex is None:
            leaves = [bytes.fromhex(tx.txid()) for tx in self.transactions]
            self._merkle_root_hex = merkle_root(leaves).hex()
        return self._merkle_root_hex

    def header_dict(self):
        return {
            "height": self.height,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root_hex,
            "target": self.target,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
        }

    def header_bytes(self) -> bytes:
        return json.dumps(self.header_dict(), sort_keys=True, separators=(",", ":")).encode()

    def hash(self) -> str:
        return sha256d(self.header_bytes()).hex()

    def to_dict(self):
        return {
            "header": self.header_dict(),
            "transactions": [tx.to_dict() for tx in self.transactions],
        }

    @staticmethod
    def from_dict(d):
        h = d["header"]
        block = Block(
            h["height"],
            h["prev_hash"],
            [Transaction.from_dict(t) for t in d["transactions"]],
            h["target"],
            timestamp=h["timestamp"],
            nonce=h["nonce"],
        )
        return block

    @staticmethod
    def genesis(reward_address, target, amount=1000):
        coinbase = Transaction.new_coinbase(reward_address, amount, height=0, extra="genesis")
        return Block(0, GENESIS_PREV_HASH, [coinbase], target, timestamp=0.0, nonce=0)
