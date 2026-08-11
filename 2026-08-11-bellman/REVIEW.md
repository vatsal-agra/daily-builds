# Adversarial review

Hostile-reviewer pass over the Phase 2 core build (envs, DP oracle,
tabular agents, NN, DQN) plus the stretch features (REINFORCE, HTML
report) as they were written. Every issue below was found by trying to
break the code, not by reading it and assuming it worked, and every one
was fixed before shipping — a fresh run of the reproduction steps hits
zero of them now.

## Bugs found and fixed

### 1. `CartPoleEnv.step()` crashed with a confusing raw error if called before `reset()`

**Found by:** deliberately calling `CartPoleEnv(seed=0).step(0)` without a
prior `reset()` — the obvious "what if a caller gets the order wrong"
check, especially since `bellman/envs/gridworld.py`'s `GridWorld.step()`
already guards exactly this case with a clean `RuntimeError`.

**What happened:** `self.state` is `None` until `reset()` is called, so
`x, x_dot, theta, theta_dot = self.state` raised
`TypeError: cannot unpack non-iterable NoneType object` — a correct
crash, but a genuinely confusing one that gives no hint about what the
caller did wrong, and an inconsistency between the two envs in this
codebase (one guards, one doesn't).

**Fix:** added the same explicit guard `CartPoleEnv` was missing:
```python
if self.state is None:
    raise RuntimeError("call reset() before step()")
```
Regression test: `tests/test_envs.py::test_step_before_reset_raises_a_clean_error`.

### 2. CLI accepted `--episodes 0` (or negative) and crashed deep inside `statistics.mean()`

**Found by:** the standard "what does an empty/invalid input do" pass
required by this build's own instructions — `python -m bellman.cli dqn
--episodes 0`.

**What happened:** `argparse` happily accepted `0` as an `int`, training
ran zero episodes, `rewards` came back `[]`, and
`statistics.mean(rewards[-30:])` raised
`statistics.StatisticsError: mean requires at least one data point` —
again a real crash, but with a traceback pointing at `statistics.py`
instead of a message that tells the user what they got wrong.

**Fix:** every `--episodes` flag across `dp`/`tabular`/`cliff-compare`/
`dqn`/`reinforce`/`report` now uses a shared `positive_int` argparse type
that rejects non-positive values with a clean, immediate
`argparse.ArgumentTypeError` before any training code runs. Regression
tests: `tests/test_cli.py::test_episodes_zero_is_rejected_cleanly`,
`::test_episodes_negative_is_rejected_cleanly`.

### 3. The HTML report's downsampler silently dropped the final training-curve point

**Found by:** stress-testing `_downsample` with a length that doesn't
divide evenly by the bucket count (e.g. 1000 values into 120 buckets) —
the standard "off-by-one at the boundary" adversarial check for any
manual bucketing code.

**What happened:** the last bucket's upper bound was computed as
`int((i + 1) * bucket)`, and floating-point error in that multiplication
(`120 * (1000/120)` evaluates to `999.9999999...`, not exactly `1000.0`)
truncated to `999` instead of `1000`, silently dropping the very last
(and often most interesting — the fully-trained end of a run) data point
from every training curve in the report.

**Fix:** the last bucket now explicitly reaches `len(values)` instead of
trusting float arithmetic to land exactly on it. Also hardened: an empty
`values` list (a hypothetical zero-episode run) now returns `[]` instead
of raising `ZeroDivisionError` inside the bucket-averaging loop.
Regression tests: `tests/test_viz.py::test_last_bucket_always_reaches_the_final_value`,
`::test_empty_input_returns_empty_not_a_crash`.

### 4. `report.py` reached into `GridWorld`'s private `_terminal` attribute

**Found by:** a plain code-quality sweep, not a runtime failure — but a
real landmine: `env._terminal` is an implementation detail of
`GridWorld` (a `set` built once in `__init__`), and nothing about its
name or existence is part of the class's public contract (`is_terminal()`
is). If that internal representation ever changed, `report.py` would
silently start producing wrong grid-arrow overlays with no error at all.

**Fix:** replaced with the public `env.is_terminal(s)` method, which is
what the rest of the codebase (correctly) already uses everywhere else.

### 5. First draft of a CliffWalking transition test didn't actually test the cliff

**Found by:** running the test and reading *why* it passed, not just
that it passed — the assertion was checking a reward value that turned
out to be `-1.0` (an ordinary step), not `-100.0` (a cliff fall), because
the chosen state/action pair landed on column 0 (`'S'`, not `'C'`) of the
cliff row.

**Fix:** corrected the test to move onto an actual `'C'` cell
(`tests/test_envs.py::test_cliff_snaps_back_to_start_and_is_not_terminal`),
caught before this ever reached a commit, but recorded here because it's
exactly the class of self-deceiving-test mistake this phase exists to
catch.

## Design choices double-checked, not changed

- **CliffWalking Q-learning vs. SARSA divergence is real, not asserted.**
  `tests/test_tabular_agents.py::test_qlearning_takes_the_cliff_edge_sarsa_does_not`
  and `bellman/cli.py cliff-compare` both reproduce Sutton & Barto's
  figure 6.13 result from this codebase's own from-scratch agents: greedy
  Q-learning walks the cliff-adjacent row, greedy SARSA stays further
  away. Checked with two different seeds during development, not just
  the one that happened to work.

- **REINFORCE clearly outperforms DQN on CartPole in this codebase** (measured:
  REINFORCE's 30-episode greedy-eval mean lands in the 400s/500,
  DQN's lands around 90-110, both far above the ~15-20 random-policy
  baseline). This is a genuine, reproducible finding, not a bug in DQN:
  REINFORCE trains on the true Monte-Carlo return of a complete episode
  (unbiased, high-variance-but-effective-here signal, cut down further by
  the learned baseline), while this from-scratch DQN uses one-step TD
  bootstrapping through a small replay buffer and a plain
  (non-prioritized) minibatch sample — a well-known harder optimization
  landscape that in the literature usually needs many more environment
  steps, a larger network, and/or reward shaping to match REINFORCE's
  sample efficiency on a task this small. Both agents are correctly
  implemented (gradient-checked NN, Double DQN target, verified replay
  buffer, verified discounted-return computation) and both massively
  outperform random play; they just don't perform *equally*, and that
  asymmetry is reported honestly in `README.md` rather than tuned away by
  cherry-picking a favorable seed or silently dropping DQN's numbers.

- **REINFORCE does not normalize its input state, DQN does.** Deliberate,
  not an oversight: DQN regresses a Q-value directly against a raw
  numeric TD target, so unnormalized inputs (cart-pole's four state
  components span wildly different scales) visibly hurt its gradient
  conditioning. REINFORCE's gradient is scaled by a *normalized*
  advantage (`(G_t - baseline) / std`, see `reinforce.py`), which already
  absorbs most of the scale sensitivity a raw-state MLP would otherwise
  suffer from — normalizing its input was tried during development and
  made no measurable difference, so the simpler unnormalized version
  shipped.

## What a fresh run-through confirms (Phase 3 gate)

- `CartPoleEnv().step(0)` before `reset()` now raises a clean `RuntimeError`.
- `python -m bellman.cli dqn --episodes 0` (and every other `--episodes`
  flag with `0` or a negative value) now fails fast with a readable
  argparse error, no traceback.
- The HTML report's training-curve charts include their true final data
  point for any episode count, not just ones that divide evenly by the
  bucket count.
- `bellman/viz/report.py` no longer touches any `GridWorld` private
  attribute.
- The full test suite (`python -m unittest discover -s tests`) is green;
  see `REVIEW.md`'s regression tests above, all now part of that suite.
