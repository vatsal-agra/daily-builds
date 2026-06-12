# RegexLab

*Daily build, 2026-06-12 — work in progress.*

A regex engine built from scratch in pure Python (parser → Thompson NFA →
Pike VM with captures → minimized DFA), plus an interactive single-file HTML
visualizer that steps through the engine's execution character by character.

**Status:** Phase 4 (stretch + polish) complete — see [REVIEW.md](REVIEW.md) for the 12 issues found & fixed in the adversarial review and the documented deliberate divergences.

All three stretch features shipped:

- ✅ `rxlab explain PATTERN` — indented plain-English breakdown (literal runs
  collapsed, classes described, lazy/greedy spelled out)
- ✅ `rxlab gen PATTERN -n 10 --seed S` — random *verified* matching strings
  (rejection-sampled against the engine, so contradictory anchors are
  detected and reported as likely-unsatisfiable)
- ✅ `rxlab fuzz -n 2000 --seed S` — built-in differential fuzzer vs
  Python's `re` (all five APIs + DFA≡NFA), exits non-zero on divergence

Polish: `viz` pre-fills the test string with a generated match; the page has
a color legend, keyboard shortcuts (←/→/space/Home/End), DFA entry arrow,
empty-input hint, and a properly labeled "DFA fullmatch" verdict line.

- ✅ Parser + Thompson NFA: literals, `.`, escapes, classes, greedy/lazy
  quantifiers incl. `{m,n}`, alternation, groups, anchors, `\b`/`\B`
- ✅ Pike VM: `match` / `fullmatch` / `search` / `finditer` / `findall` with
  capture groups — verified against Python's `re` on 5,000 random patterns
  (zero diffs, including the post-3.7 empty-match "must advance" rule)
- ✅ DFA: subset construction + Hopcroft minimization, equivalence with the
  NFA fuzz-checked; `(a|b)*abb` minimizes to the textbook 4 states
- ✅ Interactive visualizer: `python3 -m rxlab viz PATTERN -o page.html`
  emits a self-contained page (verified in headless Chromium) — type a test
  string, step the VM, watch live threads light up in the automaton

Try it:

```sh
python3 -m rxlab search '(\d+)-(\d+)' 'call 555-1234 now'
python3 -m rxlab trace '\bcat' 'a cat'
python3 -m rxlab dfa '(a|b)*abb' --table
python3 -m rxlab viz '(a|b)*abb' -o regexlab.html --text ababb
```

See [PLAN.md](PLAN.md) for the architecture and full feature list.
Remaining: adversarial review, stretch features (explain / gen / fuzz),
polish, test suite.
