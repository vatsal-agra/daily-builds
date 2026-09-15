import unittest

from causeway.segment import ACK, FIN, SYN, Segment, checksum16


class TestChecksum(unittest.TestCase):
    def test_checksum_of_known_vector(self):
        # RFC 1071's own worked example.
        data = bytes.fromhex("0001f203f4f5f6f7")
        self.assertEqual(checksum16(data), 0x220D)

    def test_checksum_detects_single_bit_flip(self):
        data = b"the quick brown fox jumps over the lazy dog" * 3
        good = checksum16(data)
        for i in range(len(data)):
            for bit in range(8):
                corrupted = bytearray(data)
                corrupted[i] ^= 1 << bit
                self.assertNotEqual(checksum16(bytes(corrupted)), good,
                                     f"undetected flip at byte {i} bit {bit}")

    def test_odd_length_padding_handled(self):
        checksum16(b"odd")  # must not raise


class TestSegmentCodec(unittest.TestCase):
    def test_roundtrip(self):
        s = Segment(seq=12345, ack=6789, window=4096, flags=ACK, payload=b"hello world")
        raw = s.encode()
        back = Segment.decode(raw)
        self.assertEqual(back.seq, 12345)
        self.assertEqual(back.ack, 6789)
        self.assertEqual(back.window, 4096)
        self.assertEqual(back.flags, ACK)
        self.assertEqual(back.payload, b"hello world")
        self.assertTrue(back._decoded_checksum_ok)

    def test_flags(self):
        s = Segment(seq=0, ack=0, window=0, flags=SYN | ACK)
        self.assertTrue(s.is_syn)
        self.assertTrue(s.is_ack)
        self.assertFalse(s.is_fin)

    def test_seq_len(self):
        self.assertEqual(Segment(0, 0, 0, SYN).seq_len(), 1)
        self.assertEqual(Segment(0, 0, 0, FIN).seq_len(), 1)
        self.assertEqual(Segment(0, 0, 0, ACK, payload=b"abcde").seq_len(), 5)
        self.assertEqual(Segment(0, 0, 0, ACK | FIN, payload=b"ab").seq_len(), 3)
        self.assertEqual(Segment(0, 0, 0, ACK).seq_len(), 0)

    def test_corruption_detected_on_decode(self):
        s = Segment(seq=1, ack=2, window=3, flags=ACK, payload=b"payload bytes")
        raw = bytearray(s.encode())
        raw[-1] ^= 0xFF  # flip a payload byte
        back = Segment.decode(bytes(raw))
        self.assertFalse(back._decoded_checksum_ok)

    def test_decode_too_short_raises(self):
        with self.assertRaises(ValueError):
            Segment.decode(b"\x00" * 5)

    def test_empty_payload(self):
        s = Segment(seq=1, ack=1, window=100, flags=ACK)
        back = Segment.decode(s.encode())
        self.assertEqual(back.payload, b"")
        self.assertTrue(back._decoded_checksum_ok)


if __name__ == "__main__":
    unittest.main()
