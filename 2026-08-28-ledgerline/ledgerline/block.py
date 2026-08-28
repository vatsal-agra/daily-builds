"""Block header, proof-of-work mining, and block-level validation."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .crypto import sha256d
from .merkle import merkle_root
from .transaction import Transaction

MAX_TARGET = (1 << 256) - 1
GENESIS_PREV_HASH = "0" * 64


def target_from_bits(bits: int) -> int:
    """`bits` = required leading zero bits in the 256-bit hash. Higher bits
    -> smaller target -> harder to mine. This is a simplified stand-in for
    Bitcoin's compact `nBits` float encoding, chosen for readability."""
    return MAX_TARGET >> bits


def difficulty_from_bits(bits: int) -> float:
    """How many hashes-on-average it takes to find a valid nonce, expressed
    as a multiple of the easiest possible target (bits=0)."""
    return float(1 << bits)


@dataclass
class BlockHeader:
    version: int
    prev_hash: str
    merkle_root_hex: str
    timestamp: float
    bits: int
    nonce: int
    height: int

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root_hex,
            "timestamp": self.timestamp,
            "bits": self.bits,
            "nonce": self.nonce,
            "height": self.height,
        }

    @staticmethod
    def from_dict(d: dict) -> "BlockHeader":
        return BlockHeader(
            d["version"], d["prev_hash"], d["merkle_root"], d["timestamp"],
            d["bits"], d["nonce"], d["height"],
        )

    def hash_bytes(self) -> bytes:
        return sha256d(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode())

    def hash_hex(self) -> str:
        return self.hash_bytes().hex()

    def meets_target(self) -> bool:
        return int.from_bytes(self.hash_bytes(), "big") < target_from_bits(self.bits)


@dataclass
class Block:
    header: BlockHeader
    transactions: List[Transaction] = field(default_factory=list)

    def hash_hex(self) -> str:
        return self.header.hash_hex()

    def to_dict(self) -> dict:
        return {
            "header": self.header.to_dict(),
            "transactions": [tx.to_dict() for tx in self.transactions],
        }

    @staticmethod
    def from_dict(d: dict) -> "Block":
        return Block(
            header=BlockHeader.from_dict(d["header"]),
            transactions=[Transaction.from_dict(t) for t in d["transactions"]],
        )

    def compute_merkle_root(self) -> str:
        leaves = [bytes.fromhex(tx.txid()) for tx in self.transactions]
        return merkle_root(leaves).hex()

    def cumulative_work_contribution(self) -> int:
        """"Work" a single block contributes: ~ MAX_TARGET / target, i.e.
        2**bits. Summing this across a chain gives Bitcoin's chainwork."""
        return 1 << self.header.bits


def make_genesis_block(coinbase_tx: Transaction, bits: int) -> Block:
    header = BlockHeader(
        version=1, prev_hash=GENESIS_PREV_HASH, merkle_root_hex="", timestamp=0.0,
        bits=bits, nonce=0, height=0,
    )
    block = Block(header=header, transactions=[coinbase_tx])
    header.merkle_root_hex = block.compute_merkle_root()
    mine_block(block, stop_flag=lambda: False)
    return block


def mine_block(
    block: Block,
    stop_flag: Callable[[], bool],
    start_nonce: int = 0,
    max_nonce: int = 2**32,
    on_progress: Optional[Callable[[int], None]] = None,
) -> bool:
    """Search for a nonce s.t. the header hash meets its target. Mutates
    `block.header.nonce` in place. Returns True on success, False if
    `stop_flag()` became true first (e.g. a peer beat us to this block) or
    the nonce space was exhausted (re-roll timestamp and retry in that
    case — real miners do the same)."""
    target = target_from_bits(block.header.bits)
    nonce = start_nonce
    checked = 0
    while nonce < max_nonce:
        if stop_flag():
            return False
        block.header.nonce = nonce
        if int.from_bytes(block.header.hash_bytes(), "big") < target:
            return True
        nonce += 1
        checked += 1
        if on_progress and checked % 20000 == 0:
            on_progress(checked)
        if checked % 400 == 0:
            # Voluntarily yield the GIL every so often. Without this, a
            # tight CPU-bound mining loop can starve other threads (socket
            # readers processing an incoming block, the connector loop) of
            # real wall-clock time to run when several nodes' miner threads
            # share one process, which manifests as far more simultaneous
            # forks than the actual network latency would ever produce —
            # `stop_flag()` above is only checked once per loop iteration,
            # so it's only as responsive as the scheduler lets this thread be.
            time.sleep(0)
    return False


def validate_block_shape(block: Block) -> Optional[str]:
    """Structural + PoW validation that doesn't need chain/UTXO context.
    Returns an error string, or None if valid."""
    if not block.transactions:
        return "block has no transactions"
    if not block.transactions[0].is_coinbase:
        return "first transaction must be coinbase"
    for tx in block.transactions[1:]:
        if tx.is_coinbase:
            return "only the first transaction may be coinbase"
    expected_root = block.compute_merkle_root()
    if expected_root != block.header.merkle_root_hex:
        return f"merkle root mismatch: header={block.header.merkle_root_hex} computed={expected_root}"
    if not block.header.meets_target():
        return "proof-of-work target not met"
    if block.header.timestamp > time.time() + 2 * 3600:
        return "block timestamp too far in the future"
    for idx, tx in enumerate(block.transactions):
        ok, err = tx.verify_signatures()
        if not ok:
            return f"transaction {idx} ({tx.txid()[:8]}) invalid: {err}"
    txids = [tx.txid() for tx in block.transactions]
    if len(set(txids)) != len(txids):
        return "duplicate transaction ids within block"
    return None
