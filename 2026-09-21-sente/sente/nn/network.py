"""The dual-head policy+value network: a shared trunk of Linear->ReLU
blocks feeding a policy head (raw logits, masked-softmax'd against legal
moves) and a value head (Linear->Tanh, scalar in [-1, 1]).

Forward and backward are both hand-written by explicitly composing the
Layer objects from layers.py -- there is no autograd graph, no
`.backward()` magic beyond "call each layer's own hand-derived backward
in reverse order and add the two heads' gradients where they rejoin the
shared trunk".
"""

from __future__ import annotations
from typing import List
import numpy as np

from .layers import Linear, ReLU, Tanh, policy_cross_entropy_loss, mse_value_loss


class PolicyValueNet:
    def __init__(self, input_dim: int, action_size: int, hidden_sizes=(64, 64), seed: int = 0):
        self.input_dim = input_dim
        self.action_size = action_size
        self.hidden_sizes = tuple(hidden_sizes)
        rng = np.random.default_rng(seed)

        self.trunk: List = []
        prev = input_dim
        for h in hidden_sizes:
            self.trunk.append(Linear(prev, h, rng))
            self.trunk.append(ReLU())
            prev = h
        trunk_out = prev

        self.policy_head = Linear(trunk_out, action_size, rng)
        self.value_fc = Linear(trunk_out, 1, rng)
        self.value_tanh = Tanh()

        # cache from the most recent forward(), needed by backward()
        self._cache = {}

    # ---- parameter (de)serialization -------------------------------
    def all_layers(self):
        return list(self.trunk) + [self.policy_head, self.value_fc]

    def get_state(self):
        state = {}
        for i, layer in enumerate(self.all_layers()):
            for name, val in layer.params().items():
                state[f"L{i}_{name}"] = val.copy()
        state["_hidden_sizes"] = np.array(self.hidden_sizes)
        state["_input_dim"] = np.array([self.input_dim])
        state["_action_size"] = np.array([self.action_size])
        return state

    def set_state(self, state):
        for i, layer in enumerate(self.all_layers()):
            keys = list(layer.params().keys())
            if not keys:
                continue
            if len(keys) == 2:
                layer.set_params(state[f"L{i}_{keys[0]}"], state[f"L{i}_{keys[1]}"])
            else:
                raise RuntimeError("unexpected layer param shape")

    # ---- forward / backward -----------------------------------------
    def forward(self, x: np.ndarray, legal_mask: np.ndarray):
        """x: (N, input_dim) float64. legal_mask: (N, action_size) bool.
        Returns (policy_probs (N,A), value (N,)).
        """
        from .layers import masked_softmax

        h = x
        acts = [h]
        for layer in self.trunk:
            h = layer.forward(h)
            acts.append(h)
        trunk_out = h

        logits = self.policy_head.forward(trunk_out)
        probs = masked_softmax(logits, legal_mask)

        v_pre = self.value_fc.forward(trunk_out)
        v = self.value_tanh.forward(v_pre)

        self._cache = {"legal_mask": legal_mask, "logits": logits, "trunk_out": trunk_out}
        return probs, v.reshape(-1)

    def loss_and_backward(self, x, legal_mask, policy_target, value_target, l2=1e-4):
        """Full forward + loss + backward in one call (used during
        training). Returns dict of scalar losses. Populates .dW/.db on
        every layer, ready for the optimizer.
        """
        probs, v = self.forward(x, legal_mask)
        logits = self._cache["logits"]

        p_loss, dlogits = policy_cross_entropy_loss(logits, legal_mask, policy_target)
        v_loss, dv = mse_value_loss(v, value_target)

        # backward through value head: dv -> tanh -> linear
        dv_pre = self.value_tanh.backward(dv)
        dtrunk_from_value = self.value_fc.backward(dv_pre)

        # backward through policy head
        dtrunk_from_policy = self.policy_head.backward(dlogits)

        dtrunk = dtrunk_from_value + dtrunk_from_policy

        # backward through shared trunk (reverse order)
        d = dtrunk
        for layer in reversed(self.trunk):
            d = layer.backward(d)

        l2_loss = 0.0
        if l2 > 0:
            for layer in self.all_layers():
                if "W" in layer.params():
                    W = layer.params()["W"]
                    l2_loss += 0.5 * l2 * np.sum(W ** 2)
                    layer.dW = layer.dW + l2 * W

        total = p_loss + v_loss + l2_loss
        return {"total": total, "policy": p_loss, "value": v_loss, "l2": l2_loss}

    def predict_one(self, x_vec: np.ndarray, legal_mask_vec: np.ndarray):
        """Convenience single-example inference for MCTS leaf evaluation."""
        probs, v = self.forward(x_vec.reshape(1, -1), legal_mask_vec.reshape(1, -1))
        return probs[0], float(v[0])
