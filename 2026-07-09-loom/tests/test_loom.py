"""End-to-end test suite exercising every feature of Loom: the autograd
engine, the Transformer, the optimizer, the tokenizer/data pipeline,
training, generation, the attention visualizer export, and the CLI."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from loom import gradcheck as gc
from loom.attention_trace import PLACEHOLDER, export as export_attention, render_html, trace
from loom.cli import main as cli_main
from loom.data import Dataset
from loom.generate import _sample_next, generate
from loom.nn import GPT, CausalSelfAttention, LayerNorm, Linear
from loom.optim import Adam
from loom.tensor import Tensor, cat, cross_entropy, gelu
from loom.tokenizer import CharTokenizer
from loom.train import compute_loss, load_checkpoint, lr_schedule, save_checkpoint, train


def _read_quickstart():
    with open(os.path.join(PROJECT_ROOT, "corpus", "quickstart.txt"), encoding="utf-8") as f:
        return f.read()


def run_cli(*argv):
    """Run the CLI in-process, capturing stdout+stderr combined (CLI errors
    are printed to stderr). Returns (exit_code, output)."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = cli_main(list(argv))
    return code, buf.getvalue()


class TestTensorEngine(unittest.TestCase):
    """Every primitive op's backward pass vs. finite differences."""

    def test_all_primitive_ops_gradient_check(self):
        for name, ok, err in gc.check_ops():
            self.assertTrue(ok, f"{name} failed gradient check: relative error {err:.2e}")

    def test_broadcasting_add_reduces_grad_correctly(self):
        a = Tensor(np.random.randn(3, 4), requires_grad=True)
        b = Tensor(np.random.randn(4), requires_grad=True)
        (a + b).sum().backward()
        self.assertEqual(a.grad.shape, (3, 4))
        self.assertEqual(b.grad.shape, (4,))
        np.testing.assert_allclose(b.grad, np.full(4, 3.0))

    def test_matmul_shapes(self):
        a = Tensor(np.random.randn(2, 3, 4), requires_grad=True)
        b = Tensor(np.random.randn(4, 5), requires_grad=True)
        out = a @ b
        self.assertEqual(out.shape, (2, 3, 5))
        out.sum().backward()
        self.assertEqual(a.grad.shape, (2, 3, 4))
        self.assertEqual(b.grad.shape, (4, 5))

    def test_softmax_rows_sum_to_one(self):
        x = Tensor(np.random.randn(5, 7))
        s = x.softmax(axis=-1)
        np.testing.assert_allclose(s.data.sum(axis=-1), np.ones(5), atol=1e-10)

    def test_pow_matches_numpy_for_various_integer_exponents(self):
        x = np.random.randn(4, 4)
        for p in [0, 1, 2, 3, 4, -1, -2]:
            got = Tensor(x) ** p
            np.testing.assert_allclose(got.data, x ** p, rtol=1e-10, atol=1e-10)

    def test_weight_reuse_accumulates_gradient_from_both_uses(self):
        # A tensor used twice in the graph (weight tying pattern) must
        # receive the SUM of gradients from both paths, not just one. Each
        # variant below builds a brand new graph from scratch -- Tensor's
        # backward() is not idempotent to call twice on a graph whose
        # intermediate .grad buffers were never reset, so reusing `out`
        # across variants would be a test bug, not an engine one.
        x_np = np.random.randn(3, 3)
        w_np = np.random.randn(3, 3)

        def grad_of(build_out):
            w = Tensor(w_np.copy(), requires_grad=True)
            x = Tensor(x_np.copy())
            build_out(x, w).backward()
            return w.grad.copy()

        g_both = grad_of(lambda x, w: (x @ w).sum() + (w @ x).sum())
        g_first_only = grad_of(lambda x, w: (x @ w).sum())
        g_second_only = grad_of(lambda x, w: (w @ x).sum())
        np.testing.assert_allclose(g_both, g_first_only + g_second_only)

    def test_cat_backward_splits_correctly(self):
        a = Tensor(np.ones((2, 3)), requires_grad=True)
        b = Tensor(np.ones((2, 2)), requires_grad=True)
        out = cat([a, b], axis=1)
        self.assertEqual(out.shape, (2, 5))
        (out * Tensor(np.arange(10).reshape(2, 5))).sum().backward()
        np.testing.assert_allclose(a.grad, np.arange(10).reshape(2, 5)[:, :3])
        np.testing.assert_allclose(b.grad, np.arange(10).reshape(2, 5)[:, 3:])


class TestNNModules(unittest.TestCase):
    def test_linear_shapes(self):
        lin = Linear(8, 16)
        x = Tensor(np.random.randn(2, 5, 8))
        out = lin(x)
        self.assertEqual(out.shape, (2, 5, 16))

    def test_layernorm_output_has_zero_mean_unit_var_before_affine(self):
        ln = LayerNorm(16)
        ln.gamma.data[:] = 1.0
        ln.beta.data[:] = 0.0
        x = Tensor(np.random.randn(4, 16) * 5 + 3)
        out = ln(x)
        np.testing.assert_allclose(out.data.mean(axis=-1), np.zeros(4), atol=1e-6)
        np.testing.assert_allclose(out.data.std(axis=-1), np.ones(4), atol=1e-3)

    def test_causal_attention_never_attends_to_future(self):
        attn = CausalSelfAttention(dim=8, n_head=2, max_len=6)
        x = Tensor(np.random.randn(1, 6, 8))
        attn(x)
        weights = attn.last_attn  # (B, n_head, T, T)
        T = 6
        for q in range(T):
            for k in range(q + 1, T):
                self.assertTrue(np.all(weights[:, :, q, k] == 0.0),
                                 f"query {q} attends to future key {k}")

    def test_attention_rows_sum_to_one(self):
        attn = CausalSelfAttention(dim=8, n_head=2, max_len=6)
        attn(Tensor(np.random.randn(1, 6, 8)))
        np.testing.assert_allclose(attn.last_attn.sum(axis=-1), np.ones((1, 2, 6)), atol=1e-8)

    def test_gpt_forward_shape(self):
        model = GPT(vocab_size=10, dim=16, n_layer=2, n_head=2, max_len=8, seed=0)
        idx = np.random.randint(0, 10, (3, 8))
        logits = model.forward(idx)
        self.assertEqual(logits.shape, (3, 8, 10))

    def test_gpt_rejects_sequence_longer_than_max_len(self):
        model = GPT(vocab_size=5, dim=8, n_layer=1, n_head=2, max_len=4, seed=0)
        with self.assertRaises(AssertionError):
            model.forward(np.zeros((1, 5), dtype=np.int64))

    def test_full_model_gradient_check(self):
        ok, worst, n = gc.check_model()
        self.assertTrue(ok, f"model gradcheck failed: worst relative error {worst:.2e} over {n} entries")

    def test_weight_tying_shares_the_same_array(self):
        model = GPT(vocab_size=10, dim=16, n_layer=1, n_head=2, max_len=8, seed=0)
        params = model.parameters()
        # tok_emb.weight must appear exactly once in the parameter list
        # (weight tying reuses the same Tensor object, not a copy).
        n_matches = sum(1 for p in params if p is model.tok_emb.weight)
        self.assertEqual(n_matches, 1)


class TestOptimizer(unittest.TestCase):
    def test_adam_minimizes_a_quadratic(self):
        target = np.array([3.0, -2.0, 5.0])
        p = Tensor(np.zeros(3), requires_grad=True)
        opt = Adam([p], lr=0.1)
        for _ in range(300):
            opt.zero_grad()
            loss = ((p - Tensor(target)) ** 2).sum()
            loss.backward()
            opt.step()
        np.testing.assert_allclose(p.data, target, atol=1e-2)

    def test_grad_clipping_reduces_norm(self):
        p = Tensor(np.zeros(3), requires_grad=True)
        p.grad = np.array([3.0, 4.0, 0.0])  # norm 5
        opt = Adam([p])
        total_norm = opt.clip_grad_norm(1.0)
        self.assertAlmostEqual(total_norm, 5.0, places=6)
        self.assertAlmostEqual(float(np.linalg.norm(p.grad)), 1.0, places=5)


class TestTokenizerAndData(unittest.TestCase):
    def test_roundtrip(self):
        tok = CharTokenizer.from_text("hello world")
        ids = tok.encode("hello world")
        self.assertEqual(tok.decode(ids), "hello world")

    def test_unknown_char_raises_value_error(self):
        tok = CharTokenizer.from_text("abc")
        with self.assertRaises(ValueError):
            tok.encode("abcZ")

    def test_save_load_roundtrip(self):
        tok = CharTokenizer.from_text("xyz123")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "vocab.json")
            tok.save(path)
            tok2 = CharTokenizer.load(path)
            self.assertEqual(tok.chars, tok2.chars)

    def test_dataset_batch_shapes_and_shift(self):
        ids = list(range(200))
        ds = Dataset(ids, block_size=10, val_fraction=0.2, seed=0)
        x, y = ds.get_batch(4, "train")
        self.assertEqual(x.shape, (4, 10))
        self.assertEqual(y.shape, (4, 10))
        # y is x shifted by exactly one position, since ids are 0..199 consecutively
        np.testing.assert_array_equal(x[:, 1:], y[:, :-1])

    def test_dataset_rejects_corpus_smaller_than_two_blocks(self):
        with self.assertRaises(ValueError):
            Dataset(list(range(50)), block_size=30, val_fraction=0.1)

    def test_dataset_val_split_always_usable(self):
        # Regression test for the Phase 3 crash: block_size large relative
        # to corpus used to produce a val split shorter than block_size+1.
        ids = list(range(600))
        ds = Dataset(ids, block_size=299, val_fraction=0.1, seed=0)
        self.assertGreaterEqual(len(ds.val_ids), 300)
        x, y = ds.get_batch(2, "val")  # must not raise
        self.assertEqual(x.shape, (2, 299))


class TestTraining(unittest.TestCase):
    def setUp(self):
        text = _read_quickstart()
        self.tok = CharTokenizer.from_text(text)
        self.ids = self.tok.encode(text)

    def test_lr_schedule_shape(self):
        lrs = [lr_schedule(s, warmup_steps=10, total_steps=100, max_lr=1.0) for s in range(120)]
        self.assertAlmostEqual(lrs[0], 0.1, places=6)          # first warmup step
        self.assertAlmostEqual(lrs[9], 1.0, places=6)          # end of warmup == max_lr
        self.assertLess(lrs[50], lrs[9])                        # cosine decay after warmup
        self.assertAlmostEqual(lrs[100], 0.1, places=6)         # min_lr_ratio floor
        self.assertTrue(all(lr <= 1.0 + 1e-9 for lr in lrs))    # never exceeds max_lr

    def test_training_reduces_loss(self):
        model = GPT(vocab_size=self.tok.vocab_size, dim=32, n_layer=2, n_head=2, max_len=32, seed=0)
        ds = Dataset(self.ids, block_size=32, val_fraction=0.15, seed=0)
        history = train(model, self.tok, ds, steps=150, batch_size=16, lr=3e-3, warmup=15,
                         eval_interval=50, verbose=False)
        self.assertLess(history[-1]["train_loss"], history[0]["train_loss"] * 0.8)

    def test_checkpoint_roundtrip_is_bit_identical(self):
        model = GPT(vocab_size=self.tok.vocab_size, dim=16, n_layer=1, n_head=2, max_len=16, seed=1)
        ds = Dataset(self.ids, block_size=16, val_fraction=0.15, seed=0)
        x, y = ds.get_batch(4, "val")
        loss_before = compute_loss(model, x, y).item()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ckpt.npz")
            save_checkpoint(path, model, self.tok)
            model2, tok2, meta = load_checkpoint(path)
            loss_after = compute_loss(model2, x, y).item()
        self.assertEqual(loss_before, loss_after)
        self.assertEqual(tok2.chars, self.tok.chars)


class TestGeneration(unittest.TestCase):
    def setUp(self):
        text = _read_quickstart()
        self.tok = CharTokenizer.from_text(text)
        self.model = GPT(vocab_size=self.tok.vocab_size, dim=16, n_layer=1, n_head=2, max_len=16, seed=0)

    def test_generate_output_length(self):
        out = generate(self.model, self.tok, prompt="Mira", max_new_tokens=30, seed=0)
        self.assertEqual(len(out), 34)

    def test_greedy_is_deterministic_regardless_of_seed(self):
        a = generate(self.model, self.tok, prompt="Mira", max_new_tokens=25, temperature=0.0, seed=1)
        b = generate(self.model, self.tok, prompt="Mira", max_new_tokens=25, temperature=0.0, seed=999)
        self.assertEqual(a, b)

    def test_generate_past_context_window_does_not_crash(self):
        out = generate(self.model, self.tok, prompt="Mira", max_new_tokens=80, temperature=0.8, seed=0)
        self.assertEqual(len(out), 84)  # far beyond max_len=16, exercises the sliding window

    def test_top_k_filtering_zeroes_out_the_rest(self):
        rng = np.random.RandomState(0)
        logits = rng.randn(10)
        counts = np.zeros(10)
        for _ in range(500):
            idx = _sample_next(logits, temperature=1.0, top_k=3, top_p=None, rng=rng)
            counts[idx] += 1
        top3 = set(np.argsort(-logits)[:3].tolist())
        sampled = set(np.nonzero(counts)[0].tolist())
        self.assertTrue(sampled.issubset(top3))

    def test_empty_prompt_still_generates(self):
        out = generate(self.model, self.tok, prompt="", max_new_tokens=10, seed=0)
        self.assertEqual(len(out), 11)


class TestAttentionTrace(unittest.TestCase):
    def setUp(self):
        text = _read_quickstart()
        self.tok = CharTokenizer.from_text(text)
        self.model = GPT(vocab_size=self.tok.vocab_size, dim=16, n_layer=2, n_head=2, max_len=16, seed=0)

    def test_trace_shapes(self):
        data = trace(self.model, self.tok, "Mira Ash")
        self.assertEqual(len(data["tokens"]), 8)
        self.assertEqual(len(data["layers"]), 2)  # n_layer
        self.assertEqual(len(data["layers"][0]), 2)  # n_head
        self.assertEqual(len(data["layers"][0][0]), 8)  # T
        self.assertEqual(len(data["layers"][0][0][0]), 8)

    def test_trace_future_positions_are_exactly_zero(self):
        data = trace(self.model, self.tok, "Mira Ash")
        mat = np.array(data["layers"][0][0])
        T = mat.shape[0]
        upper = mat[np.triu_indices(T, k=1)]
        np.testing.assert_array_equal(upper, np.zeros_like(upper))

    def test_empty_prompt_raises(self):
        with self.assertRaises(ValueError):
            trace(self.model, self.tok, "")

    def test_render_html_embeds_data_and_no_placeholder_left(self):
        data = trace(self.model, self.tok, "Mira")
        html = render_html(data)
        self.assertNotIn(PLACEHOLDER, html)
        self.assertIn('"Mira"'.replace('"', ""), "".join(data["tokens"]))  # sanity on fixture
        self.assertIn("Attention Visualizer", html)

    def test_export_writes_file_with_loss_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.html")
            data = export_attention(self.model, self.tok, "Mira", path,
                                     loss_history=[{"step": 0, "train_loss": 1.0}])
            with open(path, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("loss_history", json.dumps(data))
            self.assertGreater(len(html), 10000)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_gradcheck_command_succeeds(self):
        code, out = run_cli("gradcheck")
        self.assertEqual(code, 0)
        self.assertIn("ALL CHECKS PASSED", out)

    def test_info_command_succeeds(self):
        code, out = run_cli("info")
        self.assertEqual(code, 0)
        self.assertIn("quickstart", out)

    def test_train_then_generate_then_viz_roundtrip(self):
        ckpt = os.path.join(self.tmpdir.name, "m.npz")
        log = os.path.join(self.tmpdir.name, "log.json")
        code, out = run_cli("train", "--corpus", "quickstart", "--preset", "quickstart",
                             "--steps", "40", "--batch-size", "8", "--eval-interval", "20",
                             "--out", ckpt, "--log", log)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(ckpt))

        code, out = run_cli("generate", "--ckpt", ckpt, "--prompt", "Mira",
                             "--max-new-tokens", "20", "--seed", "0")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip().startswith("Mira"))

        viz_out = os.path.join(self.tmpdir.name, "viz.html")
        code, out = run_cli("viz", "--ckpt", ckpt, "--prompt", "Mira kept", "--out", viz_out)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(viz_out))
        self.assertGreater(os.path.getsize(viz_out), 10000)

    def test_generate_against_missing_checkpoint_fails_cleanly(self):
        code, out = run_cli("generate", "--ckpt", os.path.join(self.tmpdir.name, "nope.npz"))
        self.assertEqual(code, 1)
        self.assertIn("error:", out)

    def test_generate_bad_prompt_character_fails_cleanly(self):
        ckpt = os.path.join(self.tmpdir.name, "m.npz")
        run_cli("train", "--corpus", "quickstart", "--preset", "quickstart", "--steps", "5",
                "--batch-size", "8", "--eval-interval", "5", "--out", ckpt,
                "--log", os.path.join(self.tmpdir.name, "l.json"))
        code, out = run_cli("generate", "--ckpt", ckpt, "--prompt", "☃not-in-vocab")
        self.assertEqual(code, 1)
        self.assertIn("error:", out)

    def test_viz_empty_prompt_fails_cleanly(self):
        ckpt = os.path.join(self.tmpdir.name, "m.npz")
        run_cli("train", "--corpus", "quickstart", "--preset", "quickstart", "--steps", "5",
                "--batch-size", "8", "--eval-interval", "5", "--out", ckpt,
                "--log", os.path.join(self.tmpdir.name, "l.json"))
        code, out = run_cli("viz", "--ckpt", ckpt, "--prompt", "")
        self.assertEqual(code, 1)
        self.assertIn("error:", out)

    def test_dataset_crash_regression_fails_cleanly_via_cli(self):
        # The Phase 3 val-split crash, exercised through the real CLI entry
        # point end to end: must be a clean "error: ..." exit, not a traceback.
        code, out = run_cli("train", "--corpus", "quickstart", "--preset", "quickstart",
                             "--block-size", "299", "--steps", "5",
                             "--out", os.path.join(self.tmpdir.name, "m.npz"),
                             "--log", os.path.join(self.tmpdir.name, "l.json"))
        self.assertEqual(code, 1)
        self.assertIn("error:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
