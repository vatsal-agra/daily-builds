"""Branch predictors: static predict-not-taken, and a dynamic 2-bit
saturating-counter branch history table with a small branch-target buffer
(BTB). Both share the same interface so the pipeline can swap between them:

    predict(pc) -> (taken: bool, target: Optional[int])
    update(pc, actual_taken: bool, actual_target: int) -> None

`predict` is called for *every* fetched PC, before it's known whether the
word at that PC is even a branch (exactly like a real front-end, which
looks the fetch PC up in a BTB before decoding). `update` is called once a
control-transfer instruction actually resolves (in ID for jal, in EX for
branches/jalr).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple


class StaticNotTakenPredictor:
    """Always predicts fall-through (pc+4, not taken). No state, no
    learning -- the simplest possible predictor and the classic baseline
    every real predictor is measured against."""

    name = "static-not-taken"

    def predict(self, pc: int) -> Tuple[bool, Optional[int]]:
        return False, None

    def update(self, pc: int, actual_taken: bool, actual_target: int) -> None:
        pass  # nothing to learn


class TwoBitDynamicPredictor:
    """A direct-mapped branch-history table of 2-bit saturating counters
    (0=strongly not-taken .. 3=strongly taken), paired with a direct-mapped
    branch-target buffer. Classic Smith counter design."""

    name = "dynamic-2bit"

    def __init__(self, table_bits: int = 8):
        self.table_size = 1 << table_bits
        self._mask = self.table_size - 1
        self.counters = [1] * self.table_size  # start "weakly not-taken"
        self.btb: Dict[int, int] = {}

    def _index(self, pc: int) -> int:
        return (pc >> 2) & self._mask

    def predict(self, pc: int) -> Tuple[bool, Optional[int]]:
        idx = self._index(pc)
        taken = self.counters[idx] >= 2
        target = self.btb.get(pc) if taken else None
        # BTB miss on a predicted-taken PC we've never resolved: fall back
        # to not-taken (we have no target to jump to yet).
        if taken and target is None:
            return False, None
        return taken, target

    def update(self, pc: int, actual_taken: bool, actual_target: int) -> None:
        idx = self._index(pc)
        if actual_taken:
            self.counters[idx] = min(3, self.counters[idx] + 1)
            self.btb[pc] = actual_target
        else:
            self.counters[idx] = max(0, self.counters[idx] - 1)


def make_predictor(kind: str):
    if kind == "static":
        return StaticNotTakenPredictor()
    if kind == "dynamic":
        return TwoBitDynamicPredictor()
    raise ValueError(f"unknown predictor kind {kind!r} (expected 'static' or 'dynamic')")
