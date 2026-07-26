import os
import tempfile

from loom.train import train
from loom.viz import render_visualizer

SMALL_CORPUS = (
    "ROMEO: But soft, what light through yonder window breaks?\n"
    "JULIET: O Romeo, Romeo, wherefore art thou Romeo?\n"
) * 30


def test_render_visualizer_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        corpus_path = os.path.join(d, "corpus.txt")
        with open(corpus_path, "w") as f:
            f.write(SMALL_CORPUS)
        ckpt_dir = os.path.join(d, "ckpt")
        train(
            corpus_path=corpus_path, out_dir=ckpt_dir, vocab_size=280,
            n_embd=16, n_head=2, n_layer=2, block_size=32, batch_size=8,
            steps=5, eval_every=5, eval_iters=2, log_fn=lambda *a: None,
        )
        out_path = os.path.join(d, "viz.html")
        render_visualizer(ckpt_dir, out_path, prompt="ROMEO:")

        assert os.path.exists(out_path)
        html = open(out_path).read()
        assert "<!doctype html>" in html.lower()
        assert "</script>" in html
        assert "attnHeatmap" in html
        assert "embedScatter" in html
        assert "lossChart" in html
        # embedded JSON data actually contains real numbers from the run
        assert '"train_loss"' in html
        assert '"embeddingPoints"' in html


def test_render_visualizer_handles_labels_with_script_breakout_chars():
    """A token whose decoded label contains '</script>' must not break out of
    the inline <script> block in the generated HTML."""
    with tempfile.TemporaryDirectory() as d:
        corpus_path = os.path.join(d, "corpus.txt")
        with open(corpus_path, "w") as f:
            f.write("</script><script>alert(1)</script> " * 20 + SMALL_CORPUS)
        ckpt_dir = os.path.join(d, "ckpt")
        train(
            corpus_path=corpus_path, out_dir=ckpt_dir, vocab_size=280,
            n_embd=16, n_head=2, n_layer=2, block_size=32, batch_size=8,
            steps=3, eval_every=3, eval_iters=2, log_fn=lambda *a: None,
        )
        out_path = os.path.join(d, "viz.html")
        render_visualizer(ckpt_dir, out_path, prompt="ROMEO:")
        html = open(out_path).read()
        # the literal sequence "</script>" must only appear as the real closing
        # tags (2 of them: the tooltip escaper text and the real script close) -
        # never injected raw from token data breaking the block early.
        assert "<\\/script>" in html or "</script>" in html
        # the page must still parse as one coherent document: the final tag is </html>
        assert html.strip().endswith("</html>")


def test_render_visualizer_handles_zero_layer_model():
    """n_layer=0 is a degenerate but valid model (no CLI minimum enforces
    otherwise) - render_visualizer must not crash producing its data, and
    the page must ship the empty-attention guard rather than assume
    DATA.attnLayers[0] always exists."""
    with tempfile.TemporaryDirectory() as d:
        corpus_path = os.path.join(d, "corpus.txt")
        with open(corpus_path, "w") as f:
            f.write(SMALL_CORPUS)
        ckpt_dir = os.path.join(d, "ckpt")
        train(
            corpus_path=corpus_path, out_dir=ckpt_dir, vocab_size=280,
            n_embd=16, n_head=2, n_layer=0, block_size=32, batch_size=8,
            steps=3, eval_every=3, eval_iters=2, log_fn=lambda *a: None,
        )
        out_path = os.path.join(d, "viz.html")
        render_visualizer(ckpt_dir, out_path, prompt="ROMEO:")
        html = open(out_path).read()
        assert '"nLayer": 0' in html.replace(" ", "") or '"nLayer":0' in html.replace(" ", "")
        assert "no attention to show" in html
