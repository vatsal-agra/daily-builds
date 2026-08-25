"""Unit tests for the bencode codec, including the worked examples from
BEP 3 (https://www.bittorrent.org/beps/bep_0003.html)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import bencode


class TestEncode(unittest.TestCase):
    def test_bep3_worked_examples(self):
        self.assertEqual(bencode.encode(b"spam"), b"4:spam")
        self.assertEqual(bencode.encode(42), b"i42e")
        self.assertEqual(bencode.encode(-42), b"i-42e")
        self.assertEqual(bencode.encode(0), b"i0e")
        self.assertEqual(bencode.encode([b"spam", b"eggs"]), b"l4:spam4:eggse")
        self.assertEqual(
            bencode.encode({b"cow": b"moo", b"spam": b"eggs"}),
            b"d3:cow3:moo4:spam4:eggse",
        )
        self.assertEqual(
            bencode.encode({b"spam": [b"a", b"b"]}),
            b"d4:spaml1:a1:bee",
        )

    def test_str_is_utf8_encoded(self):
        self.assertEqual(bencode.encode("spam"), b"4:spam")
        self.assertEqual(bencode.encode("café"), b"5:caf\xc3\xa9")

    def test_dict_keys_sorted_by_raw_bytes_not_python_order(self):
        # 'z' (0x7a) sorts before '{' (0x7b) as raw bytes; make sure a
        # mixed str/bytes key set still sorts on the *encoded* bytes.
        d = {"z": 1, b"{": 2}
        encoded = bencode.encode(d)
        self.assertEqual(encoded, b"d1:zi1e1:{i2ee")

    def test_bool_rejected(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.encode(True)

    def test_empty_list_and_dict(self):
        self.assertEqual(bencode.encode([]), b"le")
        self.assertEqual(bencode.encode({}), b"de")

    def test_nested_structure(self):
        value = {b"a": [1, 2, {b"b": b"c"}], b"z": -7}
        self.assertEqual(bencode.decode(bencode.encode(value)), value)


class TestDecode(unittest.TestCase):
    def test_bep3_worked_examples(self):
        self.assertEqual(bencode.decode(b"4:spam"), b"spam")
        self.assertEqual(bencode.decode(b"i42e"), 42)
        self.assertEqual(bencode.decode(b"i-42e"), -42)
        self.assertEqual(bencode.decode(b"l4:spam4:eggse"), [b"spam", b"eggs"])
        self.assertEqual(
            bencode.decode(b"d3:cow3:moo4:spam4:eggse"),
            {b"cow": b"moo", b"spam": b"eggs"},
        )

    def test_round_trip_random_structures(self):
        import random
        rng = random.Random(1234)

        def gen(depth=0):
            choice = rng.randint(0, 3 if depth < 3 else 1)
            if choice == 0:
                return rng.randint(-10_000, 10_000)
            if choice == 1:
                return bytes(rng.randrange(256) for _ in range(rng.randint(0, 12)))
            if choice == 2:
                return [gen(depth + 1) for _ in range(rng.randint(0, 4))]
            keys = [f"k{i}".encode() for i in range(rng.randint(0, 4))]
            return {k: gen(depth + 1) for k in keys}

        for _ in range(200):
            value = gen()
            self.assertEqual(bencode.decode(bencode.encode(value)), value)

    def test_rejects_leading_zero_integer(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"i03e")

    def test_rejects_negative_zero(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"i-0e")

    def test_rejects_leading_zero_string_length(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"04:spam")

    def test_rejects_truncated_string(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"10:short")

    def test_rejects_unterminated_integer(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"i42")

    def test_rejects_unterminated_list(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"l4:spam")

    def test_rejects_unterminated_dict(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"d3:cow3:moo")

    def test_rejects_non_bytestring_dict_key(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"di1e3:fooe")

    def test_rejects_out_of_order_dict_keys(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"d4:spam3:egg3:cow3:mooe")  # "spam" before "cow"

    def test_rejects_duplicate_dict_keys(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"d3:cow3:moo3:cow3:mooe")

    def test_rejects_trailing_garbage(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"i1eXXX")

    def test_rejects_invalid_marker(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"x")

    def test_rejects_empty_input(self):
        with self.assertRaises(bencode.BencodeError):
            bencode.decode(b"")

    def test_decode_prefix_leaves_remainder(self):
        value, pos = bencode.decode_prefix(b"i5e4:spam", 0)
        self.assertEqual(value, 5)
        self.assertEqual(pos, 3)  # len("i5e")
        value2, pos2 = bencode.decode_prefix(b"i5e4:spam", pos)
        self.assertEqual(value2, b"spam")
        self.assertEqual(pos2, 9)


if __name__ == "__main__":
    unittest.main()
