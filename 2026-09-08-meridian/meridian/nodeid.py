"""The 160-bit Kademlia ID space: node IDs, content keys, and the XOR metric.

Kademlia's central idea is treating peer IDs and content keys as points in
the same 160-bit space and using XOR as a distance metric between them.
XOR distance is symmetric (d(a,b) == d(b,a)) and satisfies the triangle
inequality, which is exactly what makes the "route towards the target,
getting strictly closer each hop" lookup algorithm work.
"""
from __future__ import annotations

import hashlib

BITS = 160
MAX_ID = (1 << BITS) - 1


def sha1_int(data: bytes) -> int:
    """Hash arbitrary bytes down to a 160-bit integer (SHA-1 is exactly
    160 bits, which is why the original Kademlia paper and BitTorrent's
    mainline DHT both use it as the ID space for peers *and* content)."""
    return int.from_bytes(hashlib.sha1(data).digest(), "big")


def random_id(rng) -> int:
    """A uniformly random 160-bit ID, drawn from the given `random.Random`
    so simulation runs stay reproducible under a fixed seed."""
    return rng.getrandbits(BITS)


def distance(a: int, b: int) -> int:
    """The XOR metric: d(a, b) = a XOR b, as a 160-bit integer."""
    return a ^ b


def bucket_index(self_id: int, other_id: int) -> int | None:
    """Which k-bucket (0..159) `other_id` belongs to in `self_id`'s routing
    table: the position of the highest set bit of their XOR distance.
    Bucket i holds contacts at distance in [2**i, 2**(i+1)). Returns None
    if the two IDs are identical (no bucket -- that's "self")."""
    d = distance(self_id, other_id)
    if d == 0:
        return None
    return d.bit_length() - 1


def random_id_in_bucket(self_id: int, idx: int, rng) -> int:
    """A random ID whose bucket_index() relative to `self_id` is exactly
    `idx`. Used for periodic bucket-refresh lookups: to keep a bucket's
    contacts fresh you look up a random point inside that bucket's own
    slice of the keyspace, not just re-query contacts you already have."""
    if not (0 <= idx < BITS):
        raise ValueError(f"bucket index out of range: {idx}")
    low_bits = rng.getrandbits(idx) if idx > 0 else 0
    d = (1 << idx) | low_bits
    return self_id ^ d


def to_hex(node_id: int) -> str:
    return format(node_id, "040x")


def short(node_id: int, digits: int = 6) -> str:
    """A short display form for logs/traces -- not used for anything that
    affects routing correctness."""
    return to_hex(node_id)[:digits]
