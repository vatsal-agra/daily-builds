import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.model import TransformerLM
from loom.nn import softmax_cross_entropy


class TestModel(unittest.TestCase):
    def _model(self, **kw):
        cfg = dict(vocab_size=20, d_model=16, n_heads=4, n_layers=2, max_seq_len=10, seed=0)
        cfg.update(kw)
        return TransformerLM(**cfg)

    def test_forward_output_shape(self):
        model = self._model()
        ids = np.random.RandomState(0).randint(0, 20, size=(3, 7))
        logits, probs = model.forward(ids)
        self.assertEqual(logits.shape, (3, 7, 20))
        self.assertEqual(len(probs), 2)
        self.assertEqual(probs[0].shape, (3, 4, 7, 7))

    def test_causal_mask_future_tokens_dont_leak(self):
        """Changing a future token must not change logits at earlier positions
        (the defining invariant of a causal/autoregressive model)."""
        model = self._model()
        rng = np.random.RandomState(1)
        ids = rng.randint(0, 20, size=(1, 8))
        logits_a, _ = model.forward(ids.copy())

        ids_b = ids.copy()
        ids_b[0, -1] = (ids_b[0, -1] + 1) % 20  # perturb only the last token
        logits_b, _ = model.forward(ids_b)

        np.testing.assert_allclose(logits_a[:, :-1, :], logits_b[:, :-1, :], atol=1e-10)
        # the perturbed position's own logits may (and generally will) differ
        self.assertFalse(np.allclose(logits_a[:, -1, :], logits_b[:, -1, :]))

    def test_attention_rows_sum_to_one_and_respect_causality(self):
        model = self._model()
        ids = np.random.RandomState(2).randint(0, 20, size=(2, 6))
        _, probs = model.forward(ids)
        for layer_probs in probs:
            sums = layer_probs.sum(axis=-1)
            np.testing.assert_allclose(sums, np.ones_like(sums), atol=1e-8)
            T = layer_probs.shape[-1]
            for i in range(T):
                for j in range(i + 1, T):
                    self.assertTrue(np.all(layer_probs[..., i, j] == 0))

    def test_sequence_longer_than_max_seq_len_raises(self):
        model = self._model(max_seq_len=5)
        ids = np.zeros((1, 6), dtype=np.int64)
        with self.assertRaises(ValueError):
            model.forward(ids)

    def test_checkpoint_roundtrip_reproduces_logits(self):
        model = self._model()
        ids = np.random.RandomState(3).randint(0, 20, size=(2, 5))
        logits_before, _ = model.forward(ids)

        state = model.state_dict()
        config = model.config()
        model2 = TransformerLM.from_config(config, seed=999)  # different seed/init
        model2.load_state_dict(state)
        logits_after, _ = model2.forward(ids)

        np.testing.assert_allclose(logits_before, logits_after, atol=1e-10)

    def test_load_state_dict_shape_mismatch_raises(self):
        model = self._model()
        bad_state = {f"p{i}": np.zeros(1) for i in range(len(model.parameters()))}
        with self.assertRaises(ValueError):
            model.load_state_dict(bad_state)

    def test_weight_tying_output_head_matches_embedding(self):
        model = self._model()
        # verify the output head really is W^T of the token embedding, not a
        # separate matrix, by checking parameter count excludes a second head.
        n_params = len(model.parameters())
        # tok_emb.W, pos_emb, ln_f.(gamma,beta), and per-block: ln1(2)+attn(4 linears * 2)+ln2(2)+ff(2 linears*2)
        expected = 2 + 2 + model.n_layers * (2 + 8 + 2 + 4)
        self.assertEqual(n_params, expected)

    def test_backward_runs_without_forward_raises(self):
        model = self._model()
        dlogits = np.zeros((1, 3, 20))
        with self.assertRaises(AttributeError):
            model.backward(dlogits)

    def test_loss_finite_on_random_init(self):
        model = self._model()
        ids = np.random.RandomState(4).randint(0, 20, size=(2, 5))
        targets = np.random.RandomState(5).randint(0, 20, size=(2, 5))
        logits, _ = model.forward(ids)
        loss, dlogits = softmax_cross_entropy(logits, targets)
        self.assertTrue(np.isfinite(loss))
        self.assertTrue(np.all(np.isfinite(dlogits)))


if __name__ == "__main__":
    unittest.main()
