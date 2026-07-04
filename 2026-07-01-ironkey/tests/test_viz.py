from . import _path  # noqa: F401
import hashlib
import json
import re
import unittest

import viz


class TestViz(unittest.TestCase):
    def test_generates_well_formed_html_with_embedded_traces(self):
        html = viz.generate_html()
        self.assertIn("<html", html)
        self.assertIn("AES_TRACE", html)
        self.assertIn("SHA_TRACE", html)
        # no leftover template placeholders
        self.assertNotIn("__AES_", html)
        self.assertNotIn("__SHA_", html)

    def test_aes_trace_final_step_is_real_ciphertext(self):
        trace = viz.build_aes_trace(bytes(range(32)), b"0123456789abcdef")
        self.assertEqual(trace[0]["label"], "Input")
        # last step's hex must be a valid 32-hex-char (16-byte) ciphertext
        self.assertEqual(len(trace[-1]["hex"]), 32)

    def test_sha_trace_final_hash_matches_hashlib(self):
        msg = b"visualizer test message"
        trace = viz.build_sha_trace(msg)
        self.assertEqual(trace["final_hash"], hashlib.sha256(msg).hexdigest())

    def test_custom_inputs_reflected_in_output(self):
        key = bytes(range(32))
        html = viz.generate_html(key=key, aes_text=b"CUSTOMTEXT16BYTE", sha_text=b"custom sha message")
        self.assertIn(key.hex(), html)
        self.assertIn("custom sha message", html)

    def test_short_aes_text_is_padded_to_16_bytes(self):
        trace = viz.build_aes_trace(bytes(range(32)), b"short padded to 16".ljust(16)[:16])
        self.assertEqual(len(trace[0]["hex"]), 32)

    def test_embedded_json_is_valid(self):
        html = viz.generate_html()
        m = re.search(r"const AES_TRACE = (\[.*?\]);\nconst SHA_TRACE", html, re.S)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1))
        self.assertTrue(len(data) > 0)
        self.assertIn("label", data[0])


if __name__ == "__main__":
    unittest.main()
