# Adversarial Review

A hostile pass over the whole codebase — hunting for bugs, broken edge
cases, ugly UX, and lazy shortcuts — with every issue found either fixed
and regression-tested, or explicitly documented as a known, disclosed
limitation.

## Real bugs found and fixed

### 1. `MLP.gradcheck`'s reference loss used the wrong batch convention (CRITICAL — would have hidden a real bug)

`MLP.backward()` averages every parameter gradient over the batch
(`grads["W{i}"] = (a_prev.T @ delta) / batch`) — the convention every real
caller in this codebase relies on (DQN's TD loss, REINFORCE's policy/value
loss are both mean-over-batch). But `gradcheck()`'s own numerical
reference computed `loss = sum(out * d_out)` with **no** division by
batch. The two were checking different scalar functions: backward()
against `mean`, the finite-difference reference against `sum`. For
`batch=1` they coincide (mean == sum), which is why nothing looked wrong
until deliberately writing multi-sample gradient-check tests — every
`test_two_layer_batch`/`test_deep_network`/`test_wide_output` case failed
with a suspiciously exact `(batch-1)/batch` relative error (0.875 for
batch=8, 0.8 for batch=5, …), the unmistakable signature of a missing
`/batch`. Fixed by dividing `gradcheck()`'s reference loss by batch size
to match `backward()`'s own convention. This is exactly the kind of bug
that would have shipped silently: `test_two_layer_small_batch` (batch=1)
was green the whole time, and a single-example gradcheck is the version
someone lazily writes first.

### 2. `ReplayBuffer` backed by `collections.deque` — quietly quadratic sampling, and a stale-most-recent-item bug

Two related issues, both in the same class:

- **Performance**: `random.sample()` needs random-access indexing;
  `deque` doesn't provide O(1) indexing, so `random.sample(self.buf,
  batch_size)` on a deque degrades toward O(capacity) per draw as the
  buffer fills. Measured directly: the `ablation` command's "no_replay"
  variant (which never calls `.sample()`) finished in 1.7s while "full"
  DQN (identical episode count, replay enabled) took 10.0s — a ~6x gap
  from sampling alone, not from doing more learning work. Fixed by
  backing the buffer with a plain list plus a circular write pointer,
  making indexed sampling O(batch_size) regardless of capacity.
- **Correctness**: the "no replay" ablation variant needs "the single
  most recently pushed transition," which the code fetched via
  `self.replay.buf[-1]`. That's only correct for an unbounded or
  never-wrapped buffer — once a ring buffer wraps and starts overwriting
  from index 0, `buf[-1]` means "whatever last occupied that slot",
  not "most recently pushed." Fixed by tracking `self.last` explicitly
  in `push()`, independent of where in the ring buffer.the item landed.
  Regression test: `test_last_is_correct_even_after_wraparound`.

### 3. `MLP.forward()`/`backward()` crashed on plain Python list input

`forward()` called `x.ndim` before coercing `x` to a numpy array, so
`mlp.forward([[1,2,3],[4,5,6]])` — completely reasonable, undocumented-as-
forbidden usage — raised `AttributeError: 'list' object has no attribute
'ndim'` instead of just working (or failing with a clear message).
`backward()` had the same gap for `d_out`. No *current* production call
site happened to hit this (every caller in `dqn.py`/`reinforce.py`
explicitly wraps in `np.asarray` first), but it's exactly the kind of
"technically an API, never actually exercised the way a caller would
reasonably use it" gap this review exists to catch — found by directly
probing the public method with the input its own docstring says it
accepts (`"x: (batch, in_dim) or (in_dim,)"`, no mention of "numpy array
only"). Fixed by coercing with `np.asarray(x, dtype=np.float64)` at the
top of both methods.

### 4. `ReinforceAgent.update([], [], [])` fell through to a raw matmul error

`run_episode()` already guards against calling `update()` on a zero-step
episode (`if learn and states:`), so this wasn't reachable from the
training loop — but the public `update()` method itself, called directly
with an empty episode, crashed with a confusing
`ValueError: matmul: Input operand 1 has a mismatch in its core
dimension...` three function calls deep instead of failing at the
boundary with a message that names the actual problem. Fixed with an
explicit up-front check and a clear `ValueError`.

## UX / CLI polish

### 5. Negative `--episodes`/`--n-seeds` silently "succeeded" with nonsense output

`--episodes -5` didn't error — `range(-5)` is just an empty loop, so
training silently ran 0 real episodes, then printed `"Q-learning: -5
episodes in 0.00s"` followed by a *false* "policy does not match optimal"
verification failure (comparing an untrained, all-zero Q-table against
value iteration), with exit code 0 the whole time. That's a much worse
failure mode than a crash: a script consuming this CLI's exit code would
have reported success. Fixed with an explicit non-negative check in
`main()` (`_validate_args`) covering every episode-count and seed-count
flag across all six subcommands, surfaced via `parser.error()` (clean
usage message, exit code 2) rather than deep inside training code.

## Design decisions made honest, not hidden

### 6. Cliff Walking "hugs the edge" detection needed a real metric, not `any()`

An early version of the cliff-walking divergence check used `any(r ==
edge_row for r, c in path)` to decide whether a policy's path "hugs the
cliff edge." That's wrong: both the risky Q-learning path (which walks
the *entire* edge row) and the safe SARSA path (which only *touches* the
edge row briefly on the way up from start and down to the goal — both are
adjacent to the cliff row by construction) satisfy `any()`, so the check
couldn't actually distinguish them (`diverged` came back `False` even on
a run that had visibly reproduced the textbook divergence). Replaced with
`edge_fraction` — what fraction of the path's *interior* cells lie in the
edge row — and a >50% threshold. On the reference run: Q-learning's path
is 100% edge row, SARSA's is 12%.

### 7. DQN ablation needed multiple seeds, not one, to say anything honest

An early single-seed run of the ablation showed `no_target` DQN
outperforming `full` DQN on final eval return (310.6 vs 151.3) — the
*opposite* of the expected result, purely because DQN training variance
on a single seed is large enough to flip the ranking. Reporting that one
number would have been a real "looks like a finding, isn't" trap.
Rewrote `ablation` to run every variant across `n_seeds` (default 3) and
report mean ± std of both the final eval return *and* a max-drawdown
instability metric (largest drop from any earlier training-curve peak —
catches "learned fine, then collapsed" even on a run whose *final* number
happens to land fine). Across seeds, `no_target`'s drawdown (168.4 ± 192.6)
is both far larger and far less consistent than `full`'s (45.0 ± 13.2) —
an honest, seed-robust signal instead of a single noisy number.

## Verified, not just asserted

- Tabular Q-learning/SARSA convergence is checked against an *exact*
  value-iteration solve (`bellman/value_iteration.py`), not "reward went
  up" — and the check is a **rollout-return** comparison (does the
  learned greedy policy actually realize the optimal discounted return
  from the start state), not a raw action-table comparison, because
  harmless tie-breaking on states the optimal path never visits
  (multiple state-action pairs at the true optimum) made a stricter
  per-state comparison fail even on genuinely-converged agents — confirmed
  by checking that the *value* the tied action achieves matches V*, not
  just its identity.
- The Cliff Walking on/off-policy divergence (Sutton & Barto Example 6.6)
  is reproduced structurally, not just cited: the actual generated paths
  are checked for cliff-edge-row occupancy.
- The hand-rolled MLP's backward pass is checked against central
  finite-difference numerical gradients across 5 architectures/batch
  sizes (see bug #1 above for what that caught).
- Every environment (`GridWorld`'s wall/cliff/edge bumping, absorbing
  goal, truncation; `CartPole`'s physics) is checked against either a
  hand-derived closed-form reference or a structural invariant, not just
  "it runs."
- 99/99 tests green, including CLI-level subprocess tests that exercise
  the real `python -m bellman.train` entry point (argparse wiring,
  `--help`, invalid input) rather than only the underlying functions.

## Known, disclosed limitations (not fixed — out of scope, stated plainly)

- **CartPole is treated as fully solved by DQN/REINFORCE at real episode
  counts (see README for the actual measured numbers), but a single
  training run's final performance is inherently noisy** — this is a
  documented property of the algorithms (see ablation finding #7 above),
  not a bug. The shipped commands report real numbers from real runs
  rather than cherry-picked results, and the ablation is the one place
  variance is explicitly quantified across seeds.
- Hyperparameters (`--alpha`, `--gamma`) are not range-validated (e.g.
  `--gamma 5.0` is accepted and will simply produce a mathematically
  reasonable-but-meaningless result). This matches the CLI validation
  scope of comparable projects in this repository's history: guard
  against crashes, hangs, and silently-misleading exit codes; don't
  second-guess a user's deliberately unusual RL hyperparameters.
- `GridWorld`/`CartPole` are deterministic (no stochastic transition
  noise / slip probability). This was a deliberate Plan-phase choice
  (see PLAN.md), not an oversight — it's what makes exact value iteration
  possible as ground truth for the tabular agents.
