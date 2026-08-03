import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from undertow.segment import ChecksumError, FLAG_ACK, FLAG_FIN, FLAG_SYN, Segment


class TestSegment(unittest.TestCase):
    def test_round_trip_no_payload(self):
        seg = Segment(seq=42, ack=7, flags=FLAG_SYN | FLAG_ACK, window=1000)
        decoded = Segment.decode(seg.encode())
        self.assertEqual(decoded.seq, 42)
        self.assertEqual(decoded.ack, 7)
        self.assertEqual(decoded.flags, FLAG_SYN | FLAG_ACK)
        self.assertEqual(decoded.window, 1000)
        self.assertEqual(decoded.payload, b"")

    def test_round_trip_with_payload(self):
        payload = bytes(range(256)) * 2
        seg = Segment(seq=1000, ack=2000, flags=FLAG_ACK, window=65535, payload=payload)
        decoded = Segment.decode(seg.encode())
        self.assertEqual(decoded.payload, payload)

    def test_round_trip_with_sack_blocks(self):
        seg = Segment(seq=5, ack=5, flags=FLAG_ACK, sack_blocks=[(10, 20), (30, 45)], payload=b"hi")
        decoded = Segment.decode(seg.encode())
        self.assertEqual(decoded.sack_blocks, [(10, 20), (30, 45)])
        self.assertEqual(decoded.payload, b"hi")

    def test_corrupted_segment_rejected(self):
        seg = Segment(seq=1, ack=1, flags=FLAG_ACK, payload=b"undertow")
        raw = bytearray(seg.encode())
        raw[-1] ^= 0xFF  # flip a payload bit
        with self.assertRaises(ChecksumError):
            Segment.decode(bytes(raw))

    def test_corrupted_header_rejected(self):
        seg = Segment(seq=1, ack=1, flags=FLAG_ACK, payload=b"x")
        raw = bytearray(seg.encode())
        raw[0] ^= 0x01  # flip a bit in the seq field
        with self.assertRaises(ChecksumError):
            Segment.decode(bytes(raw))

    def test_truncated_segment_rejected(self):
        with self.assertRaises(ChecksumError):
            Segment.decode(b"\x00\x01")

    def test_seq_len(self):
        self.assertEqual(Segment(flags=FLAG_SYN).seq_len(), 1)
        self.assertEqual(Segment(flags=FLAG_FIN).seq_len(), 1)
        self.assertEqual(Segment(flags=FLAG_ACK, payload=b"hello").seq_len(), 5)
        self.assertEqual(Segment(flags=FLAG_ACK).seq_len(), 0)

    def test_flag_predicates(self):
        seg = Segment(flags=FLAG_SYN | FLAG_ACK)
        self.assertTrue(seg.is_syn())
        self.assertTrue(seg.is_ack())
        self.assertFalse(seg.is_fin())
        self.assertFalse(seg.is_rst())

    def test_too_many_sack_blocks_rejected(self):
        seg = Segment(seq=1, ack=1, sack_blocks=[(1, 2), (3, 4), (5, 6), (7, 8)])
        with self.assertRaises(ValueError):
            seg.encode()


if __name__ == "__main__":
    unittest.main()
