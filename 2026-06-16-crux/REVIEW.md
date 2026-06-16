# Adversarial Review — Crux

I attacked my own solver as a hostile reviewer: correctness fuzzing, memory
behaviour, dead code, robustness/UX, and parser edge cases. The core algorithm
came out clean (10,000-formula differential fuzz vs brute force across varied
restart schedules: **zero disagreements**, every model re-verified). The
interesting findings are below — each is fixed, with a regression guarding it.

## Findings

### F1 — VSIDS heap grows without bound (memory leak in practice). **[FIXED]**
`_var_bump` pushes a fresh `(activity, var)` entry on every bump and only ever
removes entries lazily at decision time. On PHP 8→7 the order heap ballooned to
**105,458 entries for 56 variables (1883×)**. On a long industrial run this is a
real memory blow-up and slows every `heappush`/`heappop`.
*Fix:* when the heap exceeds `~30× nvars + 1024` live entries, rebuild it from
scratch containing exactly one current entry per unassigned variable. Correctness
is unaffected (lazy staleness check already tolerates any superset); memory is now
bounded by O(nvars). Regression: `test_heap_bounded`.

### F2 — `rng_seed` parameter was dead and misleading. **[FIXED]**
`Solver(..., rng_seed=...)` was accepted, stored, and **never used** — two
different seeds produced byte-identical search. Claiming a seed that does nothing
is dishonest. The solver is fully deterministic by design.
*Fix:* removed the parameter entirely from `Solver`, the CLI fuzz path, and docs.
The solver is documented as deterministic. (The fuzzer varies the *formula* and
the *restart base*, which is what actually exercises different code paths.)

### F3 — No conflict budget: the CLI could hang forever. **[FIXED]**
On a hard-enough instance `solve` would spin indefinitely with no way out — bad
for a command-line tool. There was no third "I don't know" outcome.
*Fix:* added an optional `max_conflicts` budget. When hit, `solve` returns a
result with `sat=None` (UNKNOWN); `Result.status` is `"SAT"/"UNSAT"/"UNKNOWN"`.
The CLI prints `s UNKNOWN` and exits with code 0 (SAT competition convention).
Regression: `test_conflict_budget`.

### F4 — Dead micro-guard in the propagation hot loop. **[FIXED]**
`if first != lits[1] and value(first) is TRUE:` — the `first != lits[1]` test can
never be false (all clauses have ≥2 *distinct* watched literals; units never
become `Clause` objects). It was confusing dead code in the hottest loop.
*Fix:* removed; added an `assert len(lits) >= 2` invariant at attach time.

### F5 — Pigeonhole SAT case printed nothing useful. **[FIXED]**
`crux decode pigeonhole` on a satisfiable instance (pigeons ≤ holes) printed only
a parenthetical note, not the actual placement. Lazy UX.
*Fix:* added `pigeonhole_decode` + a formatter; the SAT case now prints the
pigeon→hole assignment.

### F6 — Exit codes / output conventions were undocumented. **[FIXED]**
`solve` exits 10 (SAT) / 20 (UNSAT) — standard for SAT solvers but surprising if
undocumented (it breaks naive `&&` shell chains). 
*Fix:* documented the exit codes and `s SATISFIABLE/UNSATISFIABLE/UNKNOWN` + `v`
model lines in the README, matching the SAT competition output format.

## Items considered and deliberately left as-is
- **Clause-deletion completeness.** Aggressive `reduceDB` + restarts could in
  theory re-learn a deleted clause forever. In practice `max_learnts` grows 1.1×
  per reduction and Luby restart intervals are unbounded, so the search always
  terminates; all test instances terminate quickly. Documented, not "fixed",
  because the practical behaviour is correct and standard (this is how MiniSat
  behaves too).
- **Clause minimization is depth-1 only.** A conservative, provably-sound subset
  of MiniSat's recursive self-subsuming minimization. Leaving the recursive
  version out keeps the code auditable; correctness is fuzz-verified.

## Post-fix verification
- 10,000-formula differential fuzz: 0 mismatches (re-run after all fixes).
- Heap entries on PHP 8→7 after fix: bounded (see `test_heap_bounded`).
- Full unittest suite green; `demo.sh` runs every feature end-to-end.
