# Adversarial review

Hostile-reviewer pass over the Phase 2 core build, hunting for bugs, broken
edge cases, ugly UX, and lazy shortcuts. Every issue found below was fixed;
each fix has a regression test guarding it (see `tests/`) so it can't
silently come back.

## Bugs found and fixed

### 1. CRITICAL — `Value.backward()` recursion blows the call stack on long episodes
`autodiff.py`'s topological sort was a recursive `build(child)` DFS. A
REINFORCE episode's loss graph is one long left-associative chain of
additions (one term per timestep), and the recursion depth scales with
episode length. Confirmed by direct reproduction: a synthetic 2000-step
episode crashes with `RecursionError`, while ~900 steps barely survives
under Python's default ~1000-frame limit. Current hyperparameters
(`train_reinforce`'s `max_steps=300` default) stay under this ceiling, so it
never fired in the Phase 2 demo run — but it's a real crash cliff sitting
directly in the project's one genuinely novel component (the autodiff
engine), one hyperparameter change away from triggering. **Fix:** rewrote
`backward()`'s topological sort as an iterative, explicit-stack post-order
DFS — the exact same algorithm, no recursion, no depth ceiling. Regression
test: `test_autodiff.test_backward_does_not_recurse_on_long_chains` (5000
terms, well past the old breaking point).

### 2. Misleading UI — hardcoded "good" (green) styling regardless of outcome
`report_app.js`'s GridWorld stat-tile row computed the *note* text
conditionally (`"matches optimal exactly"` only when
`q_learning.greedy_return === optimal_return`) but hardcoded the `good`
(green-highlight) flag to `true` unconditionally right next to it — so even
a run where Q-Learning failed to converge to optimal would still render
in reassuring green. Also present on the CartPole "trained policy" tile,
which was always green regardless of how the training actually went.
**Fix:** both tiles now derive `good` from the same real condition the note
text uses (`greedy_return === optimal_return`, and `eval_mean >
baseline_mean * 2` respectively) — the color and the label can no longer
disagree with each other or with the data.

### 3. Unsolvable-by-construction GridWorld inputs failed confusingly, not clearly
`GridWorldEnv(rows=1, ...)` puts the cliff on the *only* row, so start and
goal have no row above to detour through and the goal becomes provably
unreachable. The environment didn't reject this — instead, `value_iteration`
would spin until `max_iter` and raise a generic `RuntimeError("did not
converge")`, which is technically correct but tells the caller nothing
about *why*. **Fix:** `GridWorldEnv.__init__` now validates `rows >= 2`,
`cols >= 2`, and `0 <= slip_prob <= 1` up front with a clear `ValueError`
explaining the actual constraint (a detour row must exist above the cliff).
Regression tests in `test_envs.py`.

### 4. `BlackjackEnv.step()` used a bare `assert` for a real runtime invariant
`assert not self.done` silently disappears under `python -O`, letting a
caller keep dealing cards into an already-resolved hand with no error at
all (silently wrong behavior, not even a crash). **Fix:** raises
`RuntimeError` unconditionally. Same treatment for `reset_to`'s input-range
checks (`player_total` and `dealer_showing` bounds), which were also bare
asserts guarding caller input rather than internal invariants — replaced
with `ValueError`. (The one `assert` left in `reset_to` verifies the
method's *own* card-construction arithmetic reproduces the requested state —
a genuine internal self-check, not input validation, so it stays an
assert.)

### 5. `BlackjackEnv.reset()` silently dropped natural-blackjack episodes
The original `reset()` auto-set `done = True` when the player was dealt a
natural 21 but never computed a reward for it — any training loop hitting
this branch got zero learning signal from ~4.8% of hands, silently. **Fix:**
removed the auto-resolve from `reset()` (naturals now play through the
normal hit/stick flow like any other hand, matching the simplified
no-blackjack-bonus rules the DP oracle already assumes) and added an
explicit `resolve_natural()` for callers that want traditional natural-21
handling, with correct push-on-dealer-natural logic. Covered by
`test_resolve_natural_push_on_dealer_natural` / `test_resolve_natural_win_otherwise`.

### 6. Blackjack Monte Carlo control: epsilon-soft policy doesn't match the textbook oracle
The original `mc_control` (on-policy, epsilon-greedy, epsilon decaying to a
fixed 0.05 floor) only reached ~87-89% agreement with the independently-computed
optimal policy even at 1M episodes, and diagnosis showed why: an epsilon-soft
behavior policy converges to Q_π (value under a policy that keeps exploring
forever), not Q* — a real, persistent gap, not just sampling noise (confirmed
by inspecting visit counts: thousands of samples at disputed states, yet a
consistent bias toward "stand"). This is a correctness gap in the *algorithm
choice*, not a code bug. **Fix:** implemented Monte Carlo **Exploring
Starts** (`mc_es_control`) instead — the actual method Sutton & Barto use
for this exact Blackjack example — which reaches 100% agreement at 500k
episodes. The plain epsilon-greedy `mc_control` is kept (it's a legitimate,
informative contrast documented in `mc.py`'s module docstring) but is now
exercised by dedicated tests instead of being unused, untested code.

### 7. Wasteful: `mc_control`'s `ensure()` constructed two throwaway environments per call
`ensure(state)` called `env_factory()` *twice* just to read the constant
`.actions` list — meaning two full `BlackjackEnv` objects (each with its own
`random.Random`) were allocated and immediately discarded on every single
step of every episode. Not a correctness bug, but real, easily-avoided waste
at scale. **Fix:** `actions` is read once outside the loop.

### 8. Code duplication: `train.py` had a second, hand-copied Q-Learning loop
`q_learning_with_snapshots` was a near-verbatim copy of `td.py`'s
`q_learning`, existing only to add periodic checkpointing for the HTML
viewer's scrubber. Two independent implementations of the same algorithm is
exactly the kind of thing that silently drifts (fix a bug in one, forget the
other) — a real maintainability risk even though both copies currently
agreed. **Fix:** added an optional `on_episode_end(episode, Q)` callback
hook to `td.q_learning` itself; `q_learning_with_snapshots` is now a thin
wrapper that calls the real implementation with a snapshotting callback.
There is exactly one Q-Learning loop in the project now.

### 9. `cmd_demo` hand-duplicated every subcommand's default hyperparameters
The CLI's `demo` subcommand built `argparse.Namespace(...)` objects by hand
with numbers copy-pasted from each subparser's `add_argument(..., default=...)`
— another drift risk (change a default in one place, `demo` silently runs
stale numbers, and nothing would catch it). **Fix:** `cmd_demo` now parses
`["gridworld"]`, `["cartpole"]`, etc. through the real `argparse` parser via
a small `_parsed()` helper, so it is structurally impossible for `demo` to
disagree with the actual CLI defaults.

### 10. Found while testing the fixes: a self-inflicted `NameError` regression
While removing the duplicated Q-Learning loop from `train.py` (issue #8), the
now-unused `import random` was deleted — but `_random_policy_returns` (the
CartPole random-baseline helper, added earlier in the same phase) still
needed it, breaking `cartpole`/`viz`/`demo` and 3 tests. Caught immediately
by re-running the full suite after the refactor, which is exactly why
"fix it, then re-run everything" rather than "fix it and assume it's fine"
is the rule for this phase. Fixed by restoring the import.

## Reviewed and accepted (no change needed)

- `dp.py`'s `_hit_expected_value` includes an unused-for-correctness `depth`
  parameter under `@lru_cache`, which grows the cache more than strictly
  necessary. Bounded by the (small) Blackjack state space either way — real
  but negligible, not worth the complexity of removing.
- `value_iteration`'s degenerate-input failure mode (`RuntimeError` after
  `max_iter`) is still the correct *fallback* for `slip_prob` values close to
  1.0 that make an environment technically solvable but extremely
  expensive to converge on — issue #3's fix only rejects the
  provably-unsolvable `rows<2`/`cols<2` cases outright.
- `policy_iteration`'s capped-per-sweep policy evaluation (a "modified
  policy iteration" variant, not textbook-exact full evaluation) was a
  deliberate fix already made during Phase 2 development for a real
  divergence bug (documented in `dp.py`'s own docstring) — re-reviewed here
  and confirmed still correct: it agrees with Value Iteration on both `V*`
  and the optimal rollout return in `test_dp.py`.

## Verification after fixes

Full suite: **76/76 tests green** (up from 69 — 7 new regression tests
added directly from these findings). Report regenerated and re-inspected in
headless Chromium (light + dark mode, all three tabs, CartPole animation
played) with zero console errors after every fix in this pass.
