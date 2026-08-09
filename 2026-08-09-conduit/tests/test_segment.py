import unittest

from conduit.segment import (
    FLAG_ACK,
    FLAG_FIN,
    FLAG_SYN,
    HEADER_SIZE,
    MAX_PAYLOAD,
    Segment,
    SegmentError,
)


class TestSegment(unittest.TestCase):
    def test_roundtrip_no_payload(self):
        s = Segment(seq=123, ack=456, flags=FLAG_SYN | FLAG_ACK, window=1000)
        decoded = Segment.decode(s.encode())
        self.assertEqual(decoded.seq, 123)
        self.assertEqual(decoded.ack, 456)
        self.assertEqual(decoded.flags, FLAG_SYN | FLAG_ACK)
        self.assertEqual(decoded.window, 1000)
        self.assertEqual(decoded.payload, b"")

    def test_roundtrip_with_payload(self):
        payload = b"the quick brown fox jumps over the lazy dog" * 20
        s = Segment(seq=1, ack=2, flags=FLAG_ACK, window=65535, payload=payload)
        decoded = Segment.decode(s.encode())
        self.assertEqual(decoded.payload, payload)

    def test_header_size_is_15_bytes(self):
        self.assertEqual(HEADER_SIZE, 15)

    def test_flag_helpers(self):
        s = Segment(flags=FLAG_SYN | FLAG_FIN)
        self.assertTrue(s.has(FLAG_SYN))
        self.assertTrue(s.has(FLAG_FIN))
        self.assertFalse(s.has(FLAG_ACK))
        self.assertEqual(s.flag_str(), "SYN|FIN")

    def test_seq_ack_wrap_to_32_bits(self):
        s = Segment(seq=2**32 + 5, ack=-1)
        self.assertEqual(s.seq, 5)
        self.assertEqual(s.ack, 0xFFFFFFFF)

    def test_decode_rejects_short_datagram(self):
        with self.assertRaises(SegmentError):
            Segment.decode(b"short")

    def test_decode_rejects_length_mismatch(self):
        s = Segment(seq=1, ack=1, flags=FLAG_ACK, payload=b"hello")
        raw = bytearray(s.encode())
        raw.append(0xFF)  # append an extra byte the length field doesn't account for
        with self.assertRaises(SegmentError):
            Segment.decode(bytes(raw))

    def test_decode_rejects_bad_checksum(self):
        s = Segment(seq=1, ack=1, flags=FLAG_ACK, payload=b"hello")
        raw = bytearray(s.encode())
        raw[-1] ^= 0xFF  # corrupt the last payload byte without touching length
        with self.assertRaises(SegmentError):
            Segment.decode(bytes(raw))

    def test_encode_rejects_oversized_payload(self):
        s = Segment(payload=b"x" * (MAX_PAYLOAD + 1))
        with self.assertRaises(SegmentError):
            s.encode()

    def test_max_payload_encodes_ok(self):
        s = Segment(seq=1, payload=b"x" * MAX_PAYLOAD)
        decoded = Segment.decode(s.encode())
        self.assertEqual(len(decoded.payload), MAX_PAYLOAD)


if __name__ == "__main__":
    unittest.main()
