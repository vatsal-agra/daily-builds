"""Regression test for a critical bug found during Phase 5 verification:
`bellman.cli cartpole` run twice with the identical seed produced wildly
different results (eval mean anywhere from ~40 to ~500 steps) across
separate process invocations, despite `test_pg.test_training_is_deterministic_given_seed`
passing reliably *within* a single process.

Root cause: `autodiff.Value._prev` was a `set`. `Value` has no custom
`__hash__`, so Python falls back to identity (`id()`-based) hashing, whose
value depends on each object's memory address -- which varies between
process runs (allocator state, ASLR) even with byte-identical code and
seeds. A weight `Value` is reused across every timestep of an episode, so
its `.grad` accumulates many `+=` contributions during `backward()`, and
floating-point addition is not associative for 3+ terms -- the accumulation
*order* (driven by `_prev`'s set-iteration order) changes the last bit of
the result. CartPole's chaotic nonlinear dynamics, combined with
probability-weighted action sampling, amplify that single-bit drift into
dramatically different training trajectories.

Fixed by making `_prev` a plain `tuple` (insertion-ordered, and insertion
order is itself fully determined by the deterministic sequence of Python
operations that built the graph) instead of a `set`. This test spawns real
*separate* Python processes -- exactly the scenario that caught the bug and
that no in-process test can exercise -- and asserts their outputs are
bit-for-bit identical.
"""
import subprocess
import sys
import unittest

_SCRIPT = """
from bellman.envs import CartPoleEnv
from bellman.pg import train_reinforce, evaluate

env = CartPoleEnv(max_steps=100, seed=1)
agent, rewards = train_reinforce(env, episodes=60, hidden=6, lr=0.05, gamma=0.99,
                                  max_steps=100, seed=1)
eval_env = CartPoleEnv(max_steps=200, seed=501)
eval_rewards = evaluate(eval_env, agent, episodes=10, max_steps=200, greedy=True)
print(repr((rewards, eval_rewards)))
"""


def _run_in_fresh_process():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True, text=True, timeout=120, check=True,
    )
    return eval(result.stdout.strip())


class TestCrossProcessDeterminism(unittest.TestCase):
    def test_same_seed_gives_bit_identical_results_across_processes(self):
        run_a = _run_in_fresh_process()
        run_b = _run_in_fresh_process()
        self.assertEqual(run_a, run_b,
                          "same-seed CartPole training must be bit-identical across "
                          "separate process invocations, not just within one process")


if __name__ == "__main__":
    unittest.main()
