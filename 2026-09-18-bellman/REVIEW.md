# Adversarial review

Attacking the Phase 2 build as a hostile reviewer: hunting for bugs, bad
edge cases, ugly UX, and lazy shortcuts. Every issue below is real
(reproduced first, then fixed) or explicitly investigated and found not
to matter enough to change. A fresh run-through after the fixes hits zero
of the issues listed here (Phase 5's `demo.sh` re-checks the specific
regressions).

## Bugs found and fixed

### 1. `python -m bellman.viz_export` with no arguments crashed (real, reproduced)

`build_tictactoe_section`'s own default (`train_episodes=60000`) was
tuned and verified safe (see the comment already in that function about
epsilon=0.3 vs 0.1), but `build_all()`'s default and the CLI's
`--ttt-episodes` argparse default were both left at a stale `20000` from
before that tuning pass. Running the documented one-liner
(`python -m bellman.viz_export`, no flags) used the stale 20000-episode
default and hit the "self-play agent lost a game to the perfect oracle"
assertion in ~3 of 7 random seeds I tried (confirmed by rerunning
`build_tictactoe_section(train_episodes=20000, ...)` directly across
seeds 1-5,7: real losses in 2-51 of 300 games, not zero). The advertised
"just run this" command was broken.

**Fix:** both defaults now match `build_tictactoe_section`'s own
(`60000`). Re-ran `python -m bellman.viz_export` with literally no flags
after the fix — clean, 0/300 losses both directions.

### 2. Stale `setTimeout` crashed the browser board on reset (real, reproduced)

In `visualizer/index.html`, clicking a cell scheduled the bot's reply
with a bare `setTimeout(botMove, 250)`. Clicking "reset" (or switching
side/opponent, which also calls `newGame()`) during that 250ms window
did not cancel the pending timer. When it fired, `botMove()` ran against
the *new*, empty board — and if the human's side happened to make the bot
move first on an empty board (never a state that occurs in real,
X-moves-first play), the board+player key it looked up was never in
`oracle_table` at all, throwing `Cannot read properties of undefined
(reading 'score')` in the console with no visible error to the user (the
click just silently did nothing further).

Reproduced with a scripted Playwright repro (click a cell, reset ~30ms
later, wait past 250ms): the console error fired every time before the
fix.

**Fix:** a monotonic `state.gen` counter, bumped on every `newGame()`.
Bot moves are now scheduled through `scheduleBotMove()`, which captures
the generation at schedule time and no-ops if `state.gen` has since moved
on. Re-ran the same repro, plus a 15-game randomized stress test mixing
opponent/side switches mid-game across both the oracle and self-play
paths (Playwright, random moves, both play-as-X and play-as-O): 0 console
errors.

## Investigated, not a bug

### 3. SARSA(λ) diverged to Q-values in the thousands at the originally-planned alpha=0.5

Backward-view eligibility traces with **accumulating** traces
(`E[(s,a)] += 1.0`) blow up on Cliff Walking specifically because falling
off the cliff resets to the start state, so a long, mostly-random early
episode can revisit the same (start, action) pair dozens of times before
its eligibility is ever "spent" by a backup — each revisit adds another
full unit of credit, and the accumulated trace then multiplies the next
TD error across everything still eligible. At alpha=0.5 this diverged
outright (`Q(start, ·)` in the -400 to -2000 range, no stable policy
after 500 episodes). Switched to **replacing** traces
(`E[(s,a)] = 1.0`, cap at 1 regardless of revisits) and dropped the
default alpha to 0.1 for this algorithm specifically (`sarsa.py`'s own
better-suited default is unrelated). Fixed, documented in `td.py`'s
docstring rather than silently tuned away.

### 4. Tic-Tac-Toe self-play "never loses" claim was only true against a *deterministic* oracle

The original evaluation played the self-play agent against
`minimax.best_move`, which always returns the same (first-found) action
among ties — so "200 games" was the same single game replayed 200 times,
and the deterministic self-play agent (itself always breaking its own
ties the same way) never got to demonstrate anything beyond "this one
canonical line is fine." Once I added randomized tie-breaking on both
sides (`best_move_random_tiebreak`, and randomized ties in
`SelfPlayAgent.choose_move`) to generate genuinely different optimally-
played games, the *original* hyperparameters (`alpha=0.2, epsilon=0.1,
20000 episodes`) started **actually losing** real games as O (14-48
losses per 300, reproduced across 5 seeds) — the low exploration rate
meant self-play only ever wandered into a narrow slice of the 5478
reachable boards and never corrected its value estimate for boards a
varied optimal opponent can actually steer into. This was a real gap the
old (deterministic) evaluation was hiding, not a false alarm.
**Fixed** by raising `epsilon` to 0.3 (sustained, not decayed) and
`episodes` to 60000, verified at 0 losses across 800 games total spanning
5 independent training seeds before trusting it (see the comment already
in `viz_export.py`'s `build_tictactoe_section`).

### 5. Dead code: `minimax.play()` and `SelfPlayAgent.greedy_action()`

Neither had a single caller anywhere in the package, `viz_export.py`, or
the visualizer. Removed rather than kept "just in case" — an untested,
uncalled convenience wrapper is exactly the kind of thing that silently
rots into a real bug the next time an internal API changes underneath
it.

### 6. `_MEMO`-based alpha-beta pruning (caught before it shipped)

While first writing `minimax.py` I added alpha-beta pruning on top of the
`(board, player)` memo table using the standard recursive pattern, then
caught it myself before running anything: a score returned under a
narrowed alpha-beta window can be a *bound*, not the exact minimax value,
and caching it under a plain `(board, player)` key makes it unsafe to
reuse from a *different* window without also storing the bound type
(exact/lower/upper) — a well-known class of transposition-table bug.
Tic-Tac-Toe's entire reachable state space is under 6000 boards, so plain
memoized negamax is already instant; alpha-beta bought nothing here but
the risk of a silently wrong "optimal" move. Removed it rather than doing
it properly, and said why in the module docstring so a future change
doesn't reintroduce it by "optimizing" the search.

## Explicitly out of scope for this review

- `bellman/reinforce.py` does not exist yet — it is Phase 4's stretch
  feature, reviewed once it exists rather than reviewed as a stub now.
- Deep visual polish (grid sizing on narrow phone widths, the
  algorithm-picker row wrapping to two lines under ~420px) is real but
  cosmetic, not a correctness or crash issue; addressed in Phase 4's
  polish pass, not here.

## Phase 4 addendum: building the REINFORCE stretch feature

Building `bellman/reinforce.py` (feature 5) surfaced enough real,
reproduced problems that it's worth writing up here rather than only in
code comments, in the same "investigated, not assumed" spirit as the rest
of this document. Every claim below was directly measured, not guessed.

### 7. Mountain Car defeated vanilla REINFORCE outright — swapped the task

PLAN.md originally specified Mountain Car. Before writing any training
code, I verified the physics were right: a hand-coded "push in the
direction of current velocity" heuristic solves it in ~120 steps, every
time. But a uniformly random policy gets **0 successes in 3000 tries**
within a 200-step budget (measured directly) — the reward is -1/tick with
nothing else, so an agent has to stumble into the correct two-phase
swing-then-escape strategy purely by chance before REINFORCE has a single
success to reinforce. I tried, in order: potential-based reward shaping
(Ng, Harada & Russell 1999, height-as-potential, provably policy-
invariant) — no measurable improvement, the shaping term mostly telescopes
away over a 200-step trajectory and what's left is too small relative to
the -1/tick term to matter. Dense (non-potential) height shaping — same
result. Action-repeat / frame-skip (holding a sampled action for 8 ticks,
Atari DQN's trick, to stop i.i.d.-per-tick sampling from cancelling into
dithering) — this alone gave a random policy a real, if small, success
rate (~1.5%, measured), but training on top of it still collapsed.

That collapse turned out to be a real, separate bug, caught by directly
inspecting the policy mid-training rather than only watching the success
rate: a single scalar (EMA) baseline subtracted from every timestep's
return-to-go is fine in theory (unbiased as long as it doesn't depend on
the action taken) but is a *terrible* fit when almost every episode times
out at the same fixed length — return-to-go is then dominated by "how
many ticks are left," which is nearly the same curve shape in every
episode regardless of quality, so the "advantage" ends up strongly
positive late in *every* episode and strongly negative early in *every*
episode, independent of success. Printed parameter L1 norms confirmed it:
6979 after 1500 episodes (started under 10), with the policy collapsed to
a single deterministic action. A later attempt at a proper fix (a
per-timestep running baseline, plus an entropy bonus to stop the collapse
outright — both still visible in this file's git history) still didn't
produce a working policy within a few thousand pure-Python episodes.

At that point the honest conclusion was that Mountain Car's hard-
exploration property is genuinely famous in the RL literature for
defeating vanilla policy gradient without materially more machinery
(actor-critic, or far more compute) than a from-scratch pure-Python
stretch feature can spend here — not a bug I hadn't found yet. Per
PLAN.md's own rule for required features ("if truly infeasible, replace
with one of equal size and say so"), I swapped the *task*, not the
algorithm: CartPole is the standard first benchmark for policy-gradient
methods for exactly the opposite reason (dense +1/tick reward, no
exploration wall), same continuous-state / no-Q-table shape, same hand-
rolled network and backward pass. `bellman/envs/mountaincar.py`'s
physics were correct and are a legitimate implementation, but with
nothing left in the package that uses it, it was removed rather than kept
as unused code.

### 8. CartPole itself needed batched updates, not just a task swap

The first CartPole attempt (per-episode advantage normalization: subtract
*that episode's own* mean/std return-to-go, one gradient step per
episode) was unstable in a different way — not divergence, but genuine
oscillation: average return climbing past 140, then collapsing back under
20, repeatedly, over thousands of episodes (measured, several
hyperparameter combinations). CartPole's episode lengths vary hugely
(a lucky early episode can run 10x longer than an unlucky one right
next to it), so a single episode's own mean/std is itself a noisy
estimate, and a large step taken on a noisy estimate undoes several
episodes' progress in one move. Pooling `batch_size=10` episodes' return-
to-go values before normalizing, and averaging their gradients into one
update per batch, fixed it directly: 5 training seeds, 5000 episodes
each, greedy-evaluated over 200 held-out episodes after training —
82.5%-100% success rate, 197-200 average steps survived out of a 200
maximum, every seed. `viz_export.py` additionally checks this against a
freshly-initialized (0% success) baseline and asserts the trained policy
clearly beats it, so a future regression here fails loudly instead of
quietly shipping a worse chart.
