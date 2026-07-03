import unittest

from strata.hashing import frame, hash_object, parse_frame


class TestHashing(unittest.TestCase):
    def test_frame_roundtrip(self):
        content = b"hello world"
        framed = frame("blob", content)
        obj_type, decoded = parse_frame(framed)
        self.assertEqual(obj_type, "blob")
        self.assertEqual(decoded, content)

    def test_hash_is_deterministic(self):
        self.assertEqual(hash_object("blob", b"x"), hash_object("blob", b"x"))

    def test_hash_depends_on_type(self):
        self.assertNotEqual(hash_object("blob", b"x"), hash_object("tree", b"x"))

    def test_hash_depends_on_content(self):
        self.assertNotEqual(hash_object("blob", b"x"), hash_object("blob", b"y"))

    def test_hash_is_64_hex_chars(self):
        h = hash_object("blob", b"anything")
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            frame("bogus", b"x")

    def test_parse_frame_rejects_no_header(self):
        with self.assertRaises(ValueError):
            parse_frame(b"no null byte here")

    def test_parse_frame_rejects_length_mismatch(self):
        with self.assertRaises(ValueError):
            parse_frame(b"blob 999\0short")

    def test_parse_frame_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            parse_frame(b"bogus 4\0data")


if __name__ == "__main__":
    unittest.main()
