"""Shared input validation for the training-loop entry points.

The CLI (`cli.py`'s `positive_int`) already rejects a non-positive
`--episodes` before it reaches any of these functions -- this module exists
so the same guard also holds for callers that use `bellman` as a library
directly (tests, notebooks, `train.py`), not just through the CLI. Without
it, `episodes=0` silently "succeeds" with an empty reward history and an
untrained, all-zero-initialized policy that looks like real output.
"""


def require_positive_episodes(episodes):
    if not isinstance(episodes, int) or episodes < 1:
        raise ValueError(f"episodes must be a positive integer, got {episodes!r}")
