# Adversarial review

Hostile pass over the Phase 2 core build: physics correctness, genome
invariants, GA API misuse, and CLI failure modes. Each finding below was
reproduced with a standalone repro script before being fixed, and
re-verified after the fix. All are fixed; see the affected files for the
final code.

## Physics

1. **CRITICAL — unbounded Baumgarte position-correction bias caused
   explosive, unphysical launches.** A random genome's champion after 12
   GA generations showed a torso spinning -60 rad (nearly 10 full
   rotations) and reaching 27.99 m/s implied per-frame speed, flying up
   to y=5.6m. Root cause: `_solve_point2point`'s and the contact/limit
   solvers' Baumgarte bias (`BAUMGARTE/dt * positional_error`, with
   `BAUMGARTE/dt = 48` at `dt=1/240`) had no upper bound on the
   positional error it was allowed to correct in one step. A single
   transient (a limb slamming into its angle limit, a corner briefly
   tunneling into the ground) produced a large separation that turned
   into an explosive velocity correction, which then cascaded through
   the rest of the joint chain on the following step. Fixed by clamping
   the positional error before scaling by `BAUMGARTE/dt` — the same fix
   real engines use (Box2D's `b2_maxLinearCorrection`). Verified: the
   worst-case speed/spin across a 30-genome random sweep dropped from
   28.76 m/s / 26.34 rad to 8.41 m/s / 6.50 rad, all now consistent with
   a creature tumbling once and recovering, not an energy-injection bug.

2. **CRITICAL — a fixed global motor-torque cap let tiny limbs "cheat"
   with unrealistic angular acceleration.** `RevoluteJoint` defaulted to
   `max_motor_torque=35.0` for every joint regardless of the limb it
   drove. Body plans span roughly a 4x range in segment length/width, and
   moment of inertia falls off with the square of size, so a small limb
   (mass ~0.04 kg, I ~0.00025) under the same 35 N·m cap gets
   `alpha = torque/I` in the hundred-thousands of rad/s² — evolution
   could win by discovering a limb that thrashes at extreme angular
   velocity and flings the whole creature, rather than a real gait. Fixed
   by scaling `max_motor_torque` to each joint's own child-segment inertia
   (`ALPHA_TARGET * inertia`), so every joint gets the same *angular
   acceleration* budget regardless of size. Verified with the same
   30-genome sweep (see finding 1's numbers, produced after this fix).

## Genome bounds

3. **CRITICAL (silent invariant violation) — `_repair_bounds`'s
   depth-trimming loop was a permanent no-op.** It picked "the node with
   the largest `max_subdepth()`" to prune — but `max_subdepth()` is a
   *local* subtree-height measure that strictly decreases going down any
   path from the root, so the root **always** has the largest value in
   the whole tree and is selected every time; the loop's own guard
   (`if deepest is genome.root: break`) then immediately exits having
   pruned nothing. Repro: 200 rounds of crossover pushed genome depth up
   to 10 against a documented `MAX_DEPTH=4`, with 79/200 exceeding the
   bound. Fixed by walking the actual deepest root-to-leaf chain and
   removing that leaf from its real parent. Re-verified: 300 rounds of
   crossover+mutate now stay at depth ≤ 4 and node count ≤ 14, always.

4. **`_add_limb` used the same wrong (local, not root-relative) depth
   measure** to decide which nodes were eligible for a new child,
   for the same reason as #3 — a deep leaf reports `max_subdepth()==1`
   regardless of how deep it already sits, so it looked "safe" to extend
   further. Fixed by computing real depth-from-root before filtering
   candidates.

## GA API / persistence

5. **`Population.best()` crashed (`TypeError`) if called between
   `step_generation()` and the next evaluation.** `step_generation()`
   only carries fitness forward for the elite fraction; the rest of the
   new generation starts at `fitness=None`, and `max(..., key=lambda
   ind: ind.fitness)` throws comparing `None` to a `float`. The shipped
   CLI path (`Population.run()`) happens to always evaluate before
   returning, so this didn't surface through `kinesis evolve` — but it's
   exactly the kind of API footgun that breaks the next caller. Fixed by
   making `best()` (and `save()`) defensively call `evaluate_all()`
   first (a no-op for anything already evaluated).

6. **`Population.save()` and every HTML-writing CLI command
   (`replay`/`gallery`/`fitness-chart`) crashed with a raw
   `FileNotFoundError` traceback if `--out`'s parent directory didn't
   exist** — which is especially bad for `save()`, since it happens
   *after* a potentially many-minutes-long evolve run, discarding all of
   it. Fixed by creating the parent directory (`os.makedirs(...,
   exist_ok=True)`) before every write.

7. **Malformed or missing input files (`--checkpoint`, `--genome`)
   crashed with a raw Python traceback** instead of a clean error — the
   exact failure mode called out in this repo's own `LEDGER.md` for
   *multiple* past projects (Ironkey's OAEP oracle aside, Cryptex,
   Formulate). Fixed with a `CliError` exception caught once in `main()`,
   plus format/shape validation (`_read_json`, `_load_checkpoint`,
   `_load_bare_genome`) so a checkpoint passed to `--genome` (or vice
   versa) gets a specific, readable message instead of a `KeyError`.

## Correctness edge case

8. **A numerically unstable genome producing NaN positions propagated
   NaN all the way into `fitness`, which can silently corrupt GA
   selection.** `max(individuals, key=lambda ind: ind.fitness)` treats
   every comparison against `NaN` as `False` — so if the *first*
   individual `max()` iterates over happens to have `fitness=NaN`, no
   later (genuinely finite, better) individual can ever replace it,
   because `finite > NaN` is `False`. This is iteration-order-dependent
   and would have been very hard to notice (it doesn't crash — it just
   quietly picks a numerically-broken creature as "best" some fraction of
   the time). Fixed by detecting non-finite positions before computing
   distance/fitness and returning an explicit finite sentinel
   (`fitness=-1e6`) instead of ever letting NaN reach the arithmetic.
   Verified with an injected-NaN repro.

## Documentation bug

9. `Genome.crossover`'s docstring claimed it "replaces" a subtree at the
   chosen point; the actual (and, on reflection, better) behavior is a
   graft/append — both parents' structure tends to appear in the child
   rather than one overwriting the other. Fixed the docstring to
   describe what the code does.

## Gaps found (addressed in Phase 4, not silently dropped)

- PLAN.md promised checkpoint save/load "so an evolution run can be
  paused, resumed, or replayed." Saving/loading existed
  (`Population.save/load`), but nothing in the CLI actually resumed a
  run from a checkpoint — `kinesis evolve` always started from a fresh
  random population. Completed in Phase 4 with `evolve --resume`.

## Fresh run-through after fixes

Re-ran the full pipeline end-to-end after all fixes above: `evolve` (6
generations / pop 16), then `replay`/`gallery`/`fitness-chart` against
the resulting checkpoint, then the 30-genome stability sweep and the
300-round crossover/mutate bounds check. Zero of the issues above
reproduce.
