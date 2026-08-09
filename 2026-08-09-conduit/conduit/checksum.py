"""RFC 1071 Internet checksum.

The exact one's-complement-sum-of-16-bit-words algorithm used by IP, TCP,
UDP and ICMP. Implemented straight from the RFC's pseudocode, not from a
library, and verified in tests against the RFC's own worked example.
"""


def checksum16(data: bytes) -> int:
    """Compute the RFC 1071 Internet checksum of `data`.

    Returns a 16-bit value such that appending it (as two bytes, big
    endian) to `data` and recomputing yields 0x0000 — the same invariant
    real IP/TCP/UDP checksums rely on for the receiver-side check.
    """
    if len(data) % 2 == 1:
        data = data + b"\x00"  # pad odd-length data with a zero byte

    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) | data[i + 1]
        total += word
        total = (total & 0xFFFF) + (total >> 16)  # fold carry immediately

    return (~total) & 0xFFFF


def verify16(data: bytes, expected: int) -> bool:
    """True iff `data`'s checksum matches `expected`."""
    return checksum16(data) == expected
