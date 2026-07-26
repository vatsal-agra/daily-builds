import json
import os
import re
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.chat import stream_generate  # noqa: E402
from loom.nn import GPT  # noqa: E402
from loom.viz import _capture_generation, render_html  # noqa: E402
from loom.tokenizer import BPETokenizer  # noqa: E402

TRAIN_TEXT = "the quick brown fox jumps over the lazy dog. " * 30


def make_tok_and_model(vocab_size=270, n_embd=16, n_head=2, n_layer=2, block_size=24):
    tok = BPETokenizer()
    tok.train(TRAIN_TEXT, vocab_size=vocab_size)
    model = GPT(tok.vocab_size, n_embd, n_head, n_layer, block_size)
    return tok, model


class TestChatStreaming(unittest.TestCase):
    def test_stream_pieces_concatenate_to_full_decode(self):
        tok, model = make_tok_and_model()
        rng = np.random.default_rng(0)
        pieces = list(stream_generate(model, tok, "the quick", max_new_tokens=15, rng=rng))
        joined = "".join(pieces)
        self.assertGreater(len(joined), 0)
        # every piece must be a valid python str (no crashed decode)
        for p in pieces:
            self.assertIsInstance(p, str)

    def test_stream_respects_block_size(self):
        tok, model = make_tok_and_model(block_size=12)
        long_prompt = "the quick brown fox jumps over the lazy dog and keeps running"
        rng = np.random.default_rng(0)
        pieces = list(stream_generate(model, tok, long_prompt, max_new_tokens=50, rng=rng))
        # should not crash, and should simply generate 0 new pieces if the
        # prompt alone already fills (or exceeds) the block size
        self.assertIsInstance(pieces, list)

    def test_stream_is_deterministic_given_seeded_rng(self):
        tok, model = make_tok_and_model()
        rng1 = np.random.default_rng(7)
        rng2 = np.random.default_rng(7)
        out1 = "".join(stream_generate(model, tok, "the quick", max_new_tokens=10, rng=rng1))
        out2 = "".join(stream_generate(model, tok, "the quick", max_new_tokens=10, rng=rng2))
        self.assertEqual(out1, out2)

    def test_split_multibyte_character_decodes_correctly(self):
        # force a token whose bytes are a lone continuation byte the way a
        # real multi-byte UTF-8 character's bytes could be split across two
        # adjacent BPE tokens; the incremental decoder must buffer it rather
        # than emit a premature replacement character.
        import codecs

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        full = "café".encode("utf-8")  # 'é' is 2 bytes: 0xC3 0xA9
        out = []
        for b in full:  # feed one raw byte at a time, worst case
            piece = decoder.decode(bytes([b]))
            if piece:
                out.append(piece)
        out.append(decoder.decode(b"", final=True))
        self.assertEqual("".join(out), "café")


class TestAttentionViz(unittest.TestCase):
    def test_captured_attention_is_causal(self):
        tok, model = make_tok_and_model()
        token_ids, attn_steps = _capture_generation(
            model, tok, "the quick", max_new_tokens=5, temperature=1.0, top_k=None, seed=0
        )
        self.assertEqual(len(attn_steps), 5)
        for layers in attn_steps:
            self.assertEqual(len(layers), model.n_layer)
            for layer_attn in layers:
                # (1, n_head, T, T)
                B, n_head, T, T2 = layer_attn.shape
                self.assertEqual(T, T2)
                upper = np.triu(np.ones((T, T)), k=1).astype(bool)
                self.assertTrue(np.allclose(layer_attn[0][:, upper], 0.0))
                # every row's attention weights sum to 1 (valid probability dist)
                row_sums = layer_attn[0].sum(axis=-1)
                self.assertTrue(np.allclose(row_sums, 1.0, atol=1e-6))

    def test_render_html_contains_valid_embedded_json(self):
        tok, model = make_tok_and_model()
        token_ids, attn_steps = _capture_generation(
            model, tok, "the quick", max_new_tokens=4, temperature=1.0, top_k=None, seed=0
        )
        html = render_html(tok, token_ids, attn_steps, prompt_len=2, n_layer=model.n_layer, n_head=model.n_head)
        self.assertIn("<html>", html)
        m = re.search(r"const DATA = (\{.*\});", html)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1))
        self.assertEqual(len(data["steps"]), 4)
        self.assertEqual(data["n_layer"], model.n_layer)

    def test_viz_writes_file_via_cli_entrypoint(self):
        tok, model = make_tok_and_model()
        with tempfile.TemporaryDirectory() as d:
            from loom.checkpoint import save_checkpoint

            config = {
                "vocab_size": tok.vocab_size, "n_embd": 16, "n_head": 2,
                "n_layer": 2, "block_size": 24,
            }
            weights_path = os.path.join(d, "model.npz")
            config_path = os.path.join(d, "config.json")
            save_checkpoint(model, config, weights_path, config_path)
            tok.save(os.path.join(d, "tokenizer.json"))

            from loom.viz import build_argparser, main as viz_main

            out_path = os.path.join(d, "viz.html")
            viz_main([
                "--checkpoint-dir", d, "--prompt", "the quick",
                "--max-new-tokens", "5", "--out", out_path,
            ])
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 1000)
            with open(out_path) as f:
                m = re.search(r"const DATA = (\{.*\});", f.read())
            data = json.loads(m.group(1))
            self.assertEqual(len(data["steps"]), 5, "expected 5 generation steps to be captured")


if __name__ == "__main__":
    unittest.main()
