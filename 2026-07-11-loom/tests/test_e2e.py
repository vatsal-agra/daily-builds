"""Full-pipeline smoke test at tiny scale: BPE tokenizer -> GPT training ->
generation -> checkpoint round trip -> HTML visualizer, exactly the sequence
`loom.demo.run_demo` runs at production scale. This is the test that would
catch a wiring bug between modules that per-module unit tests can't see."""
import os
import tempfile
import unittest

from loom.checkpoint import load as load_checkpoint
from loom.sample import generate
from loom.train import train
from loom.viz import render_html

CORPUS = (
    "In the village of Hollow Brook the weaver kept a loom that remembered. "
    "Every thread that passed through it carried a little of the weather, "
    "the words spoken in the room, the quiet attention of the weaver's hands. "
) * 8


class TestEndToEnd(unittest.TestCase):
    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            model, tokenizer, history = train(
                CORPUS, out_dir=d, num_merges=100, block_size=32, n_embd=16, n_head=4, n_layer=2,
                batch_size=8, steps=60, eval_every=15, seed=0, log_fn=lambda *a, **k: None,
            )
            self.assertTrue(os.path.exists(os.path.join(d, "params.npz")))
            self.assertTrue(os.path.exists(os.path.join(d, "meta.json")))
            self.assertTrue(os.path.exists(os.path.join(d, "tokenizer.json")))
            self.assertLess(history[-1]["train_loss"], history[0]["train_loss"])

            text, trace = generate(
                model, tokenizer, prompt="The loom", max_new_tokens=40,
                temperature=0.8, top_k=20, top_p=0.95, seed=0, capture_attn=True,
            )
            self.assertTrue(text.startswith("The loom"))
            self.assertEqual(len(trace), 40)

            loaded_model, loaded_tokenizer, meta = load_checkpoint(d)
            text2, _ = generate(loaded_model, loaded_tokenizer, prompt="The loom", max_new_tokens=40,
                                 temperature=0.8, top_k=20, top_p=0.95, seed=0)
            self.assertEqual(text, text2)

            html = render_html(loaded_model, loaded_tokenizer, meta, trace, prompt="The loom")
            self.assertIn("<html", html)
            self.assertIn("</script>", html)
            self.assertIn("Loom", html)
            # the loss curve must actually be rendered from real history, not fabricated
            self.assertIn("<polyline", html)
            self.assertIn("class=\"line-train\"", html)


if __name__ == "__main__":
    unittest.main()
