import unittest

from conduit.checksum import checksum16, verify16


class TestChecksum(unittest.TestCase):
    def test_rfc1071_worked_example(self):
        # RFC 1071 section 3 works this exact example by hand:
        # bytes 00 01 f2 03 f4 f5 f6 f7 -> checksum 0x220d, and appending
        # it makes the recomputed checksum come out to 0x0000.
        data = bytes([0x00, 0x01, 0xF2, 0x03, 0xF4, 0xF5, 0xF6, 0xF7])
        chk = checksum16(data)
        self.assertEqual(chk, 0x220D)
        self.assertEqual(checksum16(data + chk.to_bytes(2, "big")), 0x0000)

    def test_verify_roundtrip(self):
        for data in [b"", b"a", b"hello world", bytes(range(256)), b"\x00" * 100]:
            chk = checksum16(data)
            self.assertTrue(verify16(data, chk))
            self.assertFalse(verify16(data + b"\x01", chk))

    def test_single_bit_flip_detected(self):
        data = bytes(range(64))
        chk = checksum16(data)
        for i in range(len(data)):
            corrupted = bytearray(data)
            corrupted[i] ^= 0x01
            self.assertFalse(verify16(bytes(corrupted), chk), f"undetected flip at byte {i}")

    def test_odd_length_padding(self):
        # Odd-length input must be handled (padded) consistently between calls.
        data = bytes(range(7))
        c1 = checksum16(data)
        c2 = checksum16(data)
        self.assertEqual(c1, c2)

    def test_carry_fold(self):
        # All-0xFF words exercise the end-around-carry fold.
        data = b"\xff\xff\xff\xff"
        chk = checksum16(data)
        self.assertTrue(verify16(data, chk))


if __name__ == "__main__":
    unittest.main()
