import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from undertow.packet import (
    FLAG_ACK,
    FLAG_FIN,
    FLAG_SYN,
    HEADER_LEN,
    MAX_SACK_BLOCKS,
    Packet,
    PacketError,
    checksum16,
)


class TestChecksum(unittest.TestCase):
    def test_known_value_matches_reference_implementation(self):
        # a hand-computed reference: two 16-bit words 0x0001 and 0xF203,
        # RFC 1071 example arithmetic
        data = bytes([0x00, 0x01, 0xF2, 0x03, 0xF4, 0xF5, 0xF6, 0xF7])
        # reference computed independently with 32-bit accumulate + fold
        total = 0
        for i in range(0, len(data), 2):
            total += (data[i] << 8) | data[i + 1]
        while total >> 16:
            total = (total & 0xFFFF) + (total >> 16)
        expected = (~total) & 0xFFFF
        self.assertEqual(checksum16(data), expected)

    def test_odd_length_padded(self):
        # must not crash, and must differ from the even-length prefix
        even = checksum16(b"\x01\x02\x03\x04")
        odd = checksum16(b"\x01\x02\x03")
        self.assertIsInstance(odd, int)
        self.assertNotEqual(even, odd)

    def test_checksum_of_all_zero_is_all_ones(self):
        self.assertEqual(checksum16(b"\x00" * 16), 0xFFFF)


class TestPacketRoundTrip(unittest.TestCase):
    def test_simple_roundtrip(self):
        p = Packet(seq=42, ack=99, flags=FLAG_ACK, window=1234, payload=b"payload bytes")
        p2 = Packet.decode(p.encode())
        self.assertEqual(p2.seq, 42)
        self.assertEqual(p2.ack, 99)
        self.assertEqual(p2.flags, FLAG_ACK)
        self.assertEqual(p2.window, 1234)
        self.assertEqual(p2.payload, b"payload bytes")
        self.assertEqual(p2.sack_blocks, [])

    def test_empty_payload_roundtrip(self):
        p = Packet(seq=1, ack=1, flags=FLAG_SYN)
        p2 = Packet.decode(p.encode())
        self.assertEqual(p2.payload, b"")
        self.assertTrue(p2.is_syn)
        self.assertFalse(p2.is_fin)

    def test_sack_blocks_roundtrip(self):
        blocks = [(10, 20), (30, 40), (50, 60)]
        p = Packet(seq=1, ack=2, flags=FLAG_ACK, sack_blocks=blocks, payload=b"x")
        p2 = Packet.decode(p.encode())
        self.assertEqual(p2.sack_blocks, blocks)

    def test_flags_roundtrip(self):
        for flags in (FLAG_SYN, FLAG_ACK, FLAG_FIN, FLAG_SYN | FLAG_ACK, FLAG_FIN | FLAG_ACK):
            p = Packet(seq=0, ack=0, flags=flags)
            p2 = Packet.decode(p.encode())
            self.assertEqual(p2.flags, flags)

    def test_seq_near_32bit_max_roundtrips(self):
        p = Packet(seq=(1 << 32) - 1, ack=(1 << 32) - 2, flags=FLAG_ACK, payload=b"wrap")
        p2 = Packet.decode(p.encode())
        self.assertEqual(p2.seq, (1 << 32) - 1)
        self.assertEqual(p2.ack, (1 << 32) - 2)

    def test_max_sack_blocks_enforced(self):
        too_many = [(i, i + 1) for i in range(MAX_SACK_BLOCKS + 1)]
        p = Packet(seq=0, ack=0, sack_blocks=too_many)
        with self.assertRaises(PacketError):
            p.encode()

    def test_large_payload_roundtrip(self):
        payload = bytes((i * 7) % 256 for i in range(4000))
        p = Packet(seq=5, ack=6, flags=FLAG_ACK, payload=payload)
        p2 = Packet.decode(p.encode())
        self.assertEqual(p2.payload, payload)


class TestPacketCorruption(unittest.TestCase):
    def test_bit_flip_in_payload_detected(self):
        p = Packet(seq=1, ack=2, flags=FLAG_ACK, payload=b"integrity matters a lot here")
        raw = bytearray(p.encode())
        raw[HEADER_LEN + 3] ^= 0x01
        with self.assertRaises(PacketError):
            Packet.decode(bytes(raw))

    def test_bit_flip_in_header_detected(self):
        p = Packet(seq=1, ack=2, flags=FLAG_ACK, window=500, payload=b"hi")
        raw = bytearray(p.encode())
        raw[0] ^= 0x80  # flip high bit of seq
        with self.assertRaises(PacketError):
            Packet.decode(bytes(raw))

    def test_truncated_header_rejected(self):
        with self.assertRaises(PacketError):
            Packet.decode(b"\x00" * (HEADER_LEN - 1))

    def test_truncated_sack_blocks_rejected(self):
        p = Packet(seq=0, ack=0, sack_blocks=[(1, 2), (3, 4)])
        raw = p.encode()
        with self.assertRaises(PacketError):
            Packet.decode(raw[: HEADER_LEN + 4])  # only half of one sack block

    def test_bogus_sack_count_rejected(self):
        import struct

        from undertow.packet import HEADER_FMT

        header = struct.pack(HEADER_FMT, 0, 0, FLAG_ACK, 200, 0, 0)
        with self.assertRaises(PacketError):
            Packet.decode(header)


if __name__ == "__main__":
    unittest.main()
