# Adversarial review (Phase 3)

Hostile pass over engine, CLI and experiments. Every finding below was reproduced, then fixed.

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | `--nosie 0.3` (typo) silently ignored → user thinks they ran noise 0.3 | high (silent wrong result) | CLI rejects unknown options with an error |
| 2 | `sweep --out` (no value) crashed with a cryptic Node `path must be string` error | medium | explicit "--out expects a directory path" |
| 3 | `Flock.restore` on snapshot missing `obstacles` threw a raw `TypeError`; malformed `predators` (`x:'a'`) was **accepted** and poisoned the sim with NaN; `p.n` vs array-length mismatch only caught by accident; negative `step`/`caught` accepted | high (state corruption) | full structural validation of every snapshot field; tests for each |
| 4 | Test "kNN with duplicate positions" had a nonsense tautological assertion (`3 === 3 ? 3 : 3`) — it could never fail | medium (fake test) | replaced with real tie-break assertions |
| 5 | `sweep --noise X` silently deleted the user's noise flag; `compare --n/--mode` likewise ignored | medium | error explains what to use instead |
| 6 | Density comparison reported only means over 3 reps, no spread, so noisy differences looked like findings | medium (misleading science) | default 5 paired-seed reps, report ±std (also on the chart) and mean NN distance |
| 7 | Experiment confound: a fixed absolute link radius means sparse flocks look "fragmented" regardless of rule. Not fixable without changing meaning; documented in README rather than hidden | low | documented |
| 8 | Hot loops allocate `[dx,dy]` tuples per pair. Measured: 3000 agents = 10 ms/step metric, 14 ms topological. Acceptable for the 150–1000 agents the UI targets | low | left; noted |

Gate: re-run of the probes (`--nosie`, `--out`, corrupt snapshots, `--noise` in sweep) now all fail loudly with a clear message; the test suite covers them.
