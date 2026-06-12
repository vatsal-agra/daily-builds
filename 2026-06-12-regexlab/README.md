# RegexLab

*Daily build, 2026-06-12 — work in progress.*

A regex engine built from scratch in pure Python (parser → Thompson NFA →
Pike VM with captures → minimized DFA), plus an interactive single-file HTML
visualizer that steps through the engine's execution character by character.

**Status:** Phase 2 (core build) complete.

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
