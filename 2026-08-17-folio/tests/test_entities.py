import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from folio.entities import decode_entities


class TestEntities(unittest.TestCase):
    def test_named_with_semicolon(self):
        self.assertEqual(decode_entities("&amp;&lt;&gt;&quot;&apos;"), "&<>\"'")

    def test_numeric_decimal(self):
        self.assertEqual(decode_entities("&#65;&#66;&#67;"), "ABC")

    def test_numeric_hex(self):
        self.assertEqual(decode_entities("&#x41;&#X42;"), "AB")

    def test_unknown_entity_kept_literal(self):
        self.assertEqual(decode_entities("&madeupname;"), "&madeupname;")

    def test_bare_ampersand(self):
        self.assertEqual(decode_entities("Q&A and R&D"), "Q&A and R&D")

    def test_invalid_codepoint_becomes_replacement_char(self):
        self.assertEqual(decode_entities("&#0;"), "�")

    def test_no_ampersand_fast_path(self):
        self.assertEqual(decode_entities("plain text"), "plain text")

    def test_named_without_trailing_semicolon_still_common_legacy(self):
        # 'amp' without ';' is one of the legacy no-semicolon-required names.
        self.assertEqual(decode_entities("Tom &amp Jerry"), "Tom & Jerry")


if __name__ == "__main__":
    unittest.main()
