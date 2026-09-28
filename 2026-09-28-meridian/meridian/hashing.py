"""Chord ring math: SHA-1 identifier hashing and modular ring-interval tests.

The Chord paper uses a full m-bit SHA-1 space (m=160). We hash with real
SHA-1 and then fold the digest down to a smaller, still astronomically
large, configurable identifier space (default 32 bits -> 4.29 billion
points on the ring) so that a node's finger table has a manageable,
demo-able number of entries (m entries) instead of 160. This is a common,
honestly-documented engineering simplification of real Chord deployments
(the identifier space just needs to be large enough that collisions among
the handful of nodes/keys in a demo are practically impossible) -- the
hashing itself is real SHA-1, not a toy hash.
"""

import hashlib

DEFAULT_M_BITS = 32


def ring_size(m_bits: int) -> int:
    return 1 << m_bits


def sha1_id(data: bytes, m_bits: int = DEFAULT_M_BITS) -> int:
    """Hash `data` with real SHA-1 and fold to an m_bits-wide ring identifier."""
    digest = hashlib.sha1(data).digest()
    full = int.from_bytes(digest, "big")
    return full % ring_size(m_bits)


def node_id_for_addr(host: str, port: int, m_bits: int = DEFAULT_M_BITS) -> int:
    return sha1_id(f"{host}:{port}".encode("utf-8"), m_bits)


def key_id(key: str, m_bits: int = DEFAULT_M_BITS) -> int:
    return sha1_id(key.encode("utf-8"), m_bits)


def in_interval(x: int, a: int, b: int, m_bits: int, incl_a: bool = False, incl_b: bool = False) -> bool:
    """Is x in the ring interval between a and b (wraparound-aware)?

    By default this is the *open* interval (a, b). Set incl_a/incl_b to
    include either endpoint, matching the Chord paper's mix of
    (a, b), (a, b] and [a, b) interval tests.

    When a == b, the interval denotes the *entire* ring (this is what a
    single-node ring's own successor/predecessor pointers looks like:
    n == n.successor), so every x is "in" it except that the shared
    endpoint's membership is governed purely by incl_a/incl_b.
    """
    size = ring_size(m_bits)
    x, a, b = x % size, a % size, b % size

    if a == b:
        if x == a:
            return incl_a or incl_b
        return True

    if a < b:
        result = a < x < b
    else:  # wraps past 0
        result = x > a or x < b

    if incl_a and x == a:
        result = True
    if incl_b and x == b:
        result = True
    return result


def finger_start(node_id: int, i: int, m_bits: int) -> int:
    """start_i = (node_id + 2^i) mod 2^m_bits, for i in [0, m_bits)."""
    return (node_id + (1 << i)) % ring_size(m_bits)
