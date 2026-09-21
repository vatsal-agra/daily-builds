# REVIEW.md — Sente adversarial review (Phase 3)

This is a hostile self-review against the exact bug classes the brief
calls out for self-play/MCTS/RL implementations, plus a general hunt for
lazy shortcuts, dead code, and misleading output. Each finding below is
either a real bug (fixed, with how it was caught and how it's now
regression-tested) or an explicit "checked, not a bug" with the evidence
that was actually run to confirm it.

## Real issues found and fixed

### 1. MCTS value-backup sign/ordering bug (caught during initial implementation, before it ever shipped)

**The bug.** The first version of `MCTS._backup()` walked the path from
leaf to root and flipped the sign of `v` *after* crediting each edge:

```python
for i in reversed(range(len(actions))):
    parent.N[a] += 1
    parent.W[a] += v      # credits BEFORE flipping perspective
    v = -v
```

This is exactly the sign-error bug class the brief calls out by name.
Walking through a 1-ply backup by hand: `path=[root, leaf]`,
`actions=[a0]`. The loop credits `root.W[a0] += leaf_value` with **no**
sign flip at all, even though `leaf_value` is from the leaf's own
to-move perspective — which is the *opponent* of whoever is to move at
root. Every single-ply backup in the whole tree was crediting the wrong
side.

**How it was caught.** Before trusting the search, I wrote
`tests/test_mcts.py`: an `OracleMCTS` that plugs the independent minimax
oracle in as the "network" value function, so any wrong sign in the
search mechanics shows up as a Q value with the wrong SIGN or magnitude
even though the "network" is perfect. Working the math out by hand for
the 1-ply and 2-ply cases while writing that test surfaced the bug
directly (see the derivation now in `mcts.py`'s module docstring and the
`_backup` inline comment) before any training run was ever attempted.

**The fix.** Flip the sign *before* crediting each edge, walking from the
deepest edge up:

```python
for i in reversed(range(len(actions))):
    v = -v
    parent.N[a] += 1
    parent.W[a] += v
```

**Regression coverage.** `tests/test_mcts.py`:
`test_root_prefers_immediate_winning_move` (Q for a forced immediate win
must be ~+1), `test_root_never_looks_confident_about_a_losing_move` (Q
for the one correct block must not look like a loss; Q for any other
move, which lets the opponent force a win, must be strongly negative),
`test_empty_board_root_moves_never_look_like_a_confirmed_loss` (no
opening move from the empty board — a proven draw — should ever look
like a confirmed loss). All three pass against the fixed code and would
fail against the original ordering (verified by hand while diagnosing).

### 2. `train.py`'s `new_examples` field conflated "games" with "example tuples"

**The bug.** Once the replay buffer reached its size cap, the logged
`new_examples` count silently switched from "example tuples added this
generation" (correct, computed while the buffer was still growing) to
`config.games_per_generation` (a *count of self-play games*, not
tuples — off by roughly 8x once symmetry augmentation is counted). This
never affected training itself (the buffer's actual contents were always
correct), only a piece of reported metadata in the JSON training report.

**The fix.** Track `examples_generated_this_gen` directly by summing
`len(examples)` per self-play game, independent of buffer fullness.

### 3. Dead code: `PolicyValueNet.copy()` and `Adam.zero_grad()`

Neither was ever called anywhere in the codebase. `copy()` was a leftover
from an earlier design that considered in-memory network gating (never
implemented — see "Known limitation" below); checkpoint save/load already
covers every real need for comparing an earlier network. `zero_grad()`
was worse than merely unused: every `Layer.backward()` call **assigns a
fresh `dW`/`db` array** rather than accumulating into an existing one
(see `Linear.backward`), so even if something had called `zero_grad()` it
would have been an actual no-op — a landmine for a future reader who
might reasonably assume calling it between steps was necessary. Both
removed.

### 4. Missing guard: `MCTS(n_simulations=0)` would silently corrupt training labels

**The risk.** With zero simulations, the root's visit-count dict would be
all zeros. `visit_policy()` would then hand back an all-zero policy
target — not a crash, a **silent wrong label** landing straight in the
replay buffer, exactly the "silently compute the wrong thing" bug class
the brief warns about for the network's backward pass, but here on the
data-generation side instead. `sample_action` would also divide by a
zero total.

**The fix.** `MCTS.__init__` now raises `ValueError` immediately if
`n_simulations < 1`, converting a possible silent corruption into a loud,
immediate failure at construction time, before any search or training
ever runs.

## Checked against the brief's bug list — confirmed NOT present, with evidence

- **Off-by-one / wrong-perspective value target.** Every training example
  is `(encode(st), legal_mask(st), pi, z)` where `z =
  outcome_for(final_state, current_player(st))` — i.e. from the
  perspective of whoever was actually to move at `st`, matching
  `encode(st)`'s own perspective convention exactly. Verified directly by
  dumping a full Connect-Four-Jr self-play game and checking every
  per-ply `z` against the known final winner and each ply's mover parity
  (18/18 plies correct, see the console excerpt below).

  ```
  0 mover= 1 z=-1.0   1 mover=-1 z=1.0   ...   17 mover=-1 z=1.0   (winner=-1)
  ```

- **Terminal-state detection missing a win or draw.**
  `tests/test_games.py` checks all 8 Tic-Tac-Toe lines individually, a
  known drawn full board, and Connect-Four-Jr's horizontal/vertical/both
  diagonal directions plus a genuine non-terminal mid-game state and a
  full-board draw. 21/21 green.

- **MCTS tree reuse corrupting state between moves.** Sidestepped by
  construction rather than merely tested: `MCTS.run()` builds a brand-new
  `Node` tree from scratch on every call, and `Game` is a stateless
  collection of classmethods over immutable tuple states, so there is no
  shared mutable board object or persisted tree for a stale reference to
  corrupt. (Trade-off: some search work is thrown away between moves
  instead of reused — acceptable at Tic-Tac-Toe/Connect-Four-Jr's scale,
  called out explicitly rather than silently accepted.)

- **Replay buffer staleness.** `ReplayBuffer` is a fixed-size `deque`
  (`maxlen=`), so old generations' data is evicted automatically as new
  self-play data arrives — verified in the training run: buffer size
  climbs to the 8,000 cap by generation 6 and training continues
  sampling a mix that is dominated by recent generations from then on
  (visible in `reports/training_tictactoe.json`).

- **Dirichlet noise leaking into evaluation.** This is the one item
  given its own dedicated regression test file,
  `tests/test_eval_purity.py`, because "I read the code and the flag
  looks right" is not good enough evidence for this specific item: (a)
  `test_noise_mechanism_actually_perturbs_root_priors` proves the noise
  mixing has a real, measurable effect (so "it never leaks" isn't a
  vacuously true claim about a no-op), (b) `test_run_defaults_to_no_noise`
  locks in that `MCTS.run`'s default is the *safe* one, and (c)
  `test_net_mcts_player_calls_run_without_noise` /
  `test_pure_mcts_player_calls_run_without_noise` **spy on the actual
  call** each evaluation player makes to `MCTS.run` (monkeypatching
  `MCTS.run` itself and recording every `add_root_noise` value it was
  called with) rather than trusting a code reading. All 4 pass.

- **Symmetry-augmentation bugs.** `tests/test_games.py` checks that every
  one of Tic-Tac-Toe's up-to-8 symmetric variants keeps policy mass
  summing to 1 and keeps it off occupied cells (caught one bug in the
  *test itself* while writing it — see "Bugs caught in the tests, not the
  code" below), and that Connect-Four-Jr's horizontal mirror correctly
  swaps both the board columns and the corresponding policy entries.

- **Policy/value collapse.** Sampled 200 distinct reachable, non-terminal
  Tic-Tac-Toe states (via random playouts from the trained gen025
  network) and measured the network's own outputs directly: value
  mean/std/min/max = `0.193 / 0.448 / -0.972 / 0.997` (a real spread, not
  a constant), policy entropy over legal moves mean/std =
  `0.699 / 0.448` (varies by state, not a fixed one-hot everywhere).
  Neither head has collapsed to a degenerate constant.

- **Temperature-schedule bugs.** `sample_action`'s `temperature <= 1e-3`
  branch is a genuine argmax (not a softmax-with-a-tiny-T that could
  still spread probability across near-tied counts due to floating
  point); the `>0` branch correctly implements `N(a)^(1/T)` via
  `exp(log(N(a))/T)` with a floor under `log(0)`. Exercised implicitly by
  every self-play game (`temp_moves` plies stochastic, then greedy) and
  every evaluation game (always `temperature=0.0`, checked directly since
  `NetMCTSPlayer`/`PureMCTSPlayer`/`oracle_invariant_check`'s agent all
  call `sample_action(..., temperature=0.0, ...)`).

- **Batch/shape bugs in the from-scratch backprop that don't crash but
  silently compute the wrong gradient.** This is exactly what
  `nn/gradcheck.py` exists to catch, and it checks both individual ops in
  isolation (`ReLU`, `Tanh`, `Linear.dx/dW/db`, both losses) and the
  *whole composed network's* every parameter (`check_network`) against
  central finite differences, for both games' actual input/action
  dimensions, before any training run. All checks pass at ≤ 7e-6 relative
  error (script output reproduced in README.md). This was run and green
  before the very first real training step, not added after the fact.

## Bugs caught in the tests themselves, while writing them (worth recording honestly)

- `test_symmetries_count_and_win_preserved` originally placed policy mass
  on cells 0, 4, and 8 of a board where those exact cells were
  *occupied* — the test's own fixture was self-contradictory (a policy
  can't legally assign probability to an occupied cell) and failed for a
  reason that had nothing to do with the symmetry code. Fixed by moving
  the test's policy mass onto the board's actual empty cells.
- The first attempt at `test_root_never_looks_confident_about_a_losing_move`
  went through three invalid Tic-Tac-Toe board fixtures in a row (wrong
  piece-count parity — e.g. 3 O's and only 1 X, which is not a reachable
  legal state) before landing on a legal one. Left the final, correct
  version in the shipped test file; not evidence of a code bug, just a
  reminder that constructing valid game-state fixtures by hand is itself
  error-prone enough to double-check (`current_player`/piece-count
  assertions were added right next to each fixture for exactly this
  reason).

## Honest limitation noted, not hidden

Tic-Tac-Toe's tree is shallow enough (≤ 9 plies) that even a weak or
randomly-initialized network, combined with 50+ MCTS simulations, often
finds exact terminal values by brute search alone — so the **MCTS-guided**
cross-generation ladder in `reports/tournament_tictactoe.json` is a
surprisingly weak signal of whether the *network* itself improved
(`gen000` already scores respectably because search compensates for it).
Rather than quietly relying on the MCTS-guided numbers alone, README.md
and the tournament script report a *second*, raw-policy-only ladder
(`NetPolicyOnlyPlayer`, zero search) specifically to give an honest,
non-inflated measurement of what the network learned on its own — and
that ladder shows the real, clean jump: gen000 Elo 951.5 (statistically
tied with random's 948.5) to gen005+ Elo ~1290-1310.

## Gate

After the fixes above: `python3 -m unittest discover -s tests -v` → 25/25
green; `scripts/run_gradcheck.py` → all checks pass; a fresh, from-scratch
training + oracle-check + tournament run (same config, same seed)
reproduces byte-identical loss curves and Elo numbers to the ones
recorded in README.md, confirming determinism and that none of the fixes
changed training behavior.
