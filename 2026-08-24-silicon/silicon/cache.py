"""A configurable set-associative cache with true LRU replacement and real
tag/index/offset address decomposition. Used standalone (unit-tested against
hand-worked hit/miss sequences) and wired into the pipeline simulator's IF
and MEM stage timing.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


def _log2_exact(n: int, what: str) -> int:
    if n <= 0 or (n & (n - 1)) != 0:
        raise ValueError(f"{what} must be a power of two, got {n}")
    return n.bit_length() - 1


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0

    @property
    def accesses(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.accesses if self.accesses else 0.0

    @property
    def miss_rate(self) -> float:
        return 1.0 - self.hit_rate if self.accesses else 0.0


class Cache:
    def __init__(self, name: str, size_bytes: int, block_size: int = 16, associativity: int = 2):
        self.name = name
        self.size_bytes = size_bytes
        self.block_size = block_size
        self.associativity = associativity

        num_blocks = size_bytes // block_size
        if num_blocks % associativity != 0:
            raise ValueError("size_bytes / block_size must be a multiple of associativity")
        self.num_sets = num_blocks // associativity
        self.offset_bits = _log2_exact(block_size, "block_size")
        self.index_bits = _log2_exact(self.num_sets, "num_sets (size/block_size/assoc)")

        # one OrderedDict per set: tag -> None, ordered oldest-first (LRU at front)
        self.sets = [OrderedDict() for _ in range(self.num_sets)]
        self.stats = CacheStats()

    def _decompose(self, addr: int):
        offset = addr & ((1 << self.offset_bits) - 1)
        index = (addr >> self.offset_bits) & (self.num_sets - 1)
        tag = addr >> (self.offset_bits + self.index_bits)
        return tag, index, offset

    def access(self, addr: int) -> bool:
        """Simulate one access to `addr`. Returns True on hit, False on miss.
        Always updates LRU / stats state as a real access would."""
        tag, index, _offset = self._decompose(addr)
        s = self.sets[index]
        if tag in s:
            s.move_to_end(tag)
            self.stats.hits += 1
            return True
        self.stats.misses += 1
        s[tag] = None
        if len(s) > self.associativity:
            s.popitem(last=False)  # evict least-recently-used
        return False

    def reset_stats(self) -> None:
        self.stats = CacheStats()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Cache({self.name!r}, {self.size_bytes}B, block={self.block_size}, "
            f"assoc={self.associativity}, sets={self.num_sets}, "
            f"hit_rate={self.stats.hit_rate:.2%})"
        )
