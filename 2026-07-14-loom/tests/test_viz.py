import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom import viz
from loom.model import TransformerLM
from loom.tokenizer import BPETokenizer


def _tiny_model_and_tok(max_seq_len=10):
    tok = BPETokenizer()
    tok.train("the quick brown fox jumps over the lazy dog " * 30, vocab_size=270)
    model = TransformerLM(vocab_size=tok.vocab_size, d_model=16, n_heads=2,
                           n_layers=2, max_seq_len=max_seq_len, seed=0)
    return model, tok


class TestViz(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_renders_valid_html_with_embedded_data(self):
        model, tok = _tiny_model_and_tok(max_seq_len=32)
        out_path = os.path.join(self.tmpdir, "viz.html")
        result = viz.render("the quick brown fox", model, tok, out_path=out_path)
        self.assertEqual(result, out_path)
        with open(out_path) as f:
            html = f.read()
        self.assertIn("<html", html)
        self.assertIn("DATA", html)

    def test_prompt_longer_than_max_seq_len_does_not_crash(self):
        """Regression test: viz.render used to hardcode max_context=48 and
        crash on any model with a smaller max_seq_len, or any prompt whose
        token count exceeded max_seq_len. It must now truncate cleanly."""
        model, tok = _tiny_model_and_tok(max_seq_len=10)
        long_prompt = "the quick brown fox jumps over the lazy dog " * 5
        out_path = os.path.join(self.tmpdir, "viz.html")
        result = viz.render(long_prompt, model, tok, out_path=out_path)
        self.assertTrue(os.path.exists(result))

    def test_default_max_context_above_model_limit_does_not_crash(self):
        model, tok = _tiny_model_and_tok(max_seq_len=5)
        out_path = os.path.join(self.tmpdir, "viz.html")
        # default max_context (48) exceeds this model's max_seq_len (5)
        viz.render("the quick brown fox and then some", model, tok, out_path=out_path)
        self.assertTrue(os.path.exists(out_path))

    def test_script_tag_in_prompt_is_escaped(self):
        """Regression test: embedded JSON must not let attacker-influenceable
        token content prematurely close the surrounding <script> block."""
        model, tok = _tiny_model_and_tok(max_seq_len=64)
        payload = "the </script><script>alert(1)</script> fox"
        out_path = os.path.join(self.tmpdir, "viz.html")
        viz.render(payload, model, tok, out_path=out_path)
        with open(out_path) as f:
            html = f.read()
        self.assertNotIn("</script><script>alert(1)</script>", html)
        # the data must still be valid JSON once the escape is reversed
        start = html.index("const DATA = ") + len("const DATA = ")
        end = html.index(";\n", start)
        raw = html[start:end].replace("<\\/", "</")
        json.loads(raw)  # must not raise

    def test_missing_parent_directory_is_created(self):
        model, tok = _tiny_model_and_tok(max_seq_len=32)
        out_path = os.path.join(self.tmpdir, "nested", "subdir", "viz.html")
        result = viz.render("the quick brown fox", model, tok, out_path=out_path)
        self.assertTrue(os.path.exists(result))

    def test_renders_without_a_training_log(self):
        model, tok = _tiny_model_and_tok(max_seq_len=32)
        out_path = os.path.join(self.tmpdir, "viz.html")
        viz.render("the quick brown fox", model, tok, log_path=None, out_path=out_path)
        with open(out_path) as f:
            html = f.read()
        self.assertIn('"loss": []', html)

    def test_renders_with_a_training_log(self):
        model, tok = _tiny_model_and_tok(max_seq_len=32)
        log_path = os.path.join(self.tmpdir, "train_log.jsonl")
        with open(log_path, "w") as f:
            for step in range(5):
                f.write(json.dumps({"step": step, "loss": 5.0 - step * 0.1}) + "\n")
        out_path = os.path.join(self.tmpdir, "viz.html")
        viz.render("the quick brown fox", model, tok, log_path=log_path, out_path=out_path)
        with open(out_path) as f:
            html = f.read()
        self.assertIn('"step": 4', html)

    def test_empty_prompt_does_not_crash(self):
        model, tok = _tiny_model_and_tok(max_seq_len=32)
        out_path = os.path.join(self.tmpdir, "viz.html")
        viz.render("", model, tok, out_path=out_path)
        self.assertTrue(os.path.exists(out_path))


if __name__ == "__main__":
    unittest.main()
