"""
Bloom filter — from-scratch implementation using double hashing.

Uses FNV-1a and DJB2 variant seeds to derive k independent hash functions
from two base hashes (Kirsch-Mitzenmacher technique): h_i(x) = h1(x) + i*h2(x).
"""

import math


def _fnv1a(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x00000100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _djb2(data: bytes) -> int:
    h = 5381
    for b in data:
        h = ((h << 5) + h + b) & 0xFFFFFFFFFFFFFFFF
    return h


class BloomFilter:
    """Bit-array Bloom filter with configurable false-positive rate."""

    def __init__(self, expected_items: int = 1000, fp_rate: float = 0.01):
        self.fp_rate = fp_rate
        self.expected_items = max(1, expected_items)
        # Optimal bit count: m = -n * ln(p) / (ln(2)^2)
        m = int(math.ceil(-expected_items * math.log(fp_rate) / (math.log(2) ** 2)))
        self.m = max(8, m)
        # Optimal hash count: k = (m/n) * ln(2)
        k = int(math.ceil((self.m / self.expected_items) * math.log(2)))
        self.k = max(1, k)
        self._bits = bytearray((self.m + 7) // 8)

    def _hash_pair(self, key: bytes):
        h1 = _fnv1a(key) % self.m
        h2 = _djb2(key) % self.m
        return h1, h2

    def add(self, key: bytes) -> None:
        h1, h2 = self._hash_pair(key)
        for i in range(self.k):
            idx = (h1 + i * h2) % self.m
            self._bits[idx >> 3] |= 1 << (idx & 7)

    def may_contain(self, key: bytes) -> bool:
        h1, h2 = self._hash_pair(key)
        for i in range(self.k):
            idx = (h1 + i * h2) % self.m
            if not (self._bits[idx >> 3] & (1 << (idx & 7))):
                return False
        return True

    def to_bytes(self) -> bytes:
        """Serialize: [k:1][m:4][bits...]"""
        import struct
        return struct.pack(">BI", self.k, self.m) + bytes(self._bits)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomFilter":
        import struct
        k, m = struct.unpack_from(">BI", data, 0)
        bf = cls.__new__(cls)
        bf.k = k
        bf.m = m
        bf.fp_rate = 0.01
        bf.expected_items = 0
        header_size = struct.calcsize(">BI")
        bf._bits = bytearray(data[header_size:])
        return bf
