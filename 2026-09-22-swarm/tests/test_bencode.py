import unittest

from swarm import bencode


class TestBencode(unittest.TestCase):
    def test_int_roundtrip(self):
        for n in (0, 1, -1, 42, -42, 2**63, -(2**63)):
            self.assertEqual(bencode.decode(bencode.encode(n)), n)

    def test_int_wire_shapes(self):
        self.assertEqual(bencode.encode(0), b"i0e")
        self.assertEqual(bencode.encode(42), b"i42e")
        self.assertEqual(bencode.encode(-42), b"i-42e")

    def test_bytes_roundtrip(self):
        for b in (b"", b"hello", b"\x00\x01\xff" * 10):
            self.assertEqual(bencode.decode(bencode.encode(b)), b)

    def test_string_encodes_as_utf8_bytes(self):
        self.assertEqual(bencode.encode("spam"), b"4:spam")

    def test_list_roundtrip(self):
        val = [1, b"two", [3, b"four"], {}]
        self.assertEqual(bencode.decode(bencode.encode(val)), [1, b"two", [3, b"four"], {}])

    def test_dict_roundtrip(self):
        val = {b"a": 1, b"b": [1, 2, 3], b"c": {b"nested": b"yes"}}
        self.assertEqual(bencode.decode(bencode.encode(val)), val)

    def test_dict_keys_sorted_canonically(self):
        val = {b"zzz": 1, b"aaa": 2, b"mmm": 3}
        encoded = bencode.encode(val)
        self.assertEqual(encoded, b"d3:aaai2e3:mmmi3e3:zzzi1ee")

    def test_known_vectors(self):
        # From the original BitTorrent spec examples.
        self.assertEqual(bencode.decode(b"4:spam"), b"spam")
        self.assertEqual(bencode.decode(b"i3e"), 3)
        self.assertEqual(bencode.decode(b"l4:spam4:eggse"), [b"spam", b"eggs"])
        self.assertEqual(bencode.decode(b"d3:cow3:moo4:spam4:eggse"), {b"cow": b"moo", b"spam": b"eggs"})
        self.assertEqual(bencode.decode(b"d4:spaml1:a1:bee"), {b"spam": [b"a", b"b"]})

    def test_rejects_leading_zero_integer(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"i03e")

    def test_rejects_negative_zero(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"i-0e")

    def test_rejects_truncated_input(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"4:sp")

    def test_rejects_trailing_garbage(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"i3eXXX")

    def test_rejects_unterminated_list(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"l4:spam")

    def test_rejects_non_bytes_dict_key(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"di3ei4ee")

    def test_rejects_out_of_order_dict_keys(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"d3:zzzi1e3:aaai2ee")

    def test_encode_rejects_bool(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.encode(True)

    def test_decode_prefix_leaves_remainder(self):
        data = b"i3e" + b"garbage"
        value, pos = bencode.decode_prefix(data)
        self.assertEqual(value, 3)
        self.assertEqual(data[pos:], b"garbage")

    def test_fuzz_random_bytes_never_crash_uncaught(self):
        import random

        rng = random.Random(7)
        for _ in range(500):
            junk = rng.randbytes(rng.randint(0, 40))
            try:
                bencode.decode(junk)
            except bencode.BencodeError:
                pass  # the only acceptable outcome for garbage input


if __name__ == "__main__":
    unittest.main()
