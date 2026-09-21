"""A bounded replay buffer of (encoded_board, legal_mask, policy_target,
value_target) tuples produced by self-play. Bounded with a deque so old
generations' data ages out (staleness control -- see REVIEW.md for the
staleness bug this was checked against: without a cap, generation-0's
near-random self-play games would still be a large fraction of the
training mix many generations later, diluting the signal from better,
newer self-play).
"""

from __future__ import annotations
from collections import deque
import numpy as np


class ReplayBuffer:
    def __init__(self, max_size: int = 20000, seed: int = 0):
        self.max_size = max_size
        self.buf = deque(maxlen=max_size)
        self.rng = np.random.default_rng(seed)

    def add(self, x, legal_mask, policy, value):
        self.buf.append((x.astype(np.float64), legal_mask.astype(bool),
                          policy.astype(np.float64), float(value)))

    def add_game(self, examples):
        for x, mask, pi, z in examples:
            self.add(x, mask, pi, z)

    def __len__(self):
        return len(self.buf)

    def sample(self, batch_size: int):
        n = len(self.buf)
        idxs = self.rng.integers(0, n, size=min(batch_size, n))
        xs, masks, pis, zs = [], [], [], []
        for i in idxs:
            x, mask, pi, z = self.buf[i]
            xs.append(x)
            masks.append(mask)
            pis.append(pi)
            zs.append(z)
        return (np.stack(xs), np.stack(masks), np.stack(pis), np.array(zs))
