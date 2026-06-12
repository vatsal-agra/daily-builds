# RegexLab — a regex engine you can see think

A complete regular-expression engine written from scratch in pure Python 3
stdlib — recursive-descent parser → Thompson NFA → Pike VM with capture
groups → subset-construction DFA with Hopcroft minimization — plus an
**interactive single-file HTML visualizer**: type any test string in the
browser and step through the engine's execution character by character,
watching live threads light up in the real automaton. Think *regex101,
offline, showing you the actual machine instead of a syntax highlighter*.

Because it simulates the NFA breadth-first (no backtracking), matching is
O(len(text) × len(pattern)) — the classic ReDoS killer `(a+)+$` on sixty
`a`s answers in under a millisecond where backtracking engines take minutes.

## How to run

No dependencies (the browser tests optionally use node + Playwright).
From this folder:

```sh
# the whole tour, ending with the test suite
bash demo.sh

# match / search / fullmatch / findall, with capture groups
python3 -m rxlab search '(\d+)-(\d+)' 'call 555-1234 now'

# watch the Pike VM's thread list scan a string, in the terminal
python3 -m rxlab trace '\bcat' 'a cat'

# compile to a minimized DFA, print the state table
python3 -m rxlab dfa '(a|b)*abb' --table --text ababb

# THE showpiece: emit a self-contained interactive visualizer page
python3 -m rxlab viz '\w+@\w+\.(?:com|org)' -o regexlab.html
# then open regexlab.html — no network needed; ←/→ step, space plays

# plain-English explanation of a pattern
python3 -m rxlab explain '(\d{1,3}\.){3}\d{1,3}|localhost'

# random strings that PROVABLY match (verified through the engine)
python3 -m rxlab gen '(\d{1,3}\.){3}\d{1,3}' -n 5 --seed 42

# differential fuzz this engine against Python's re
python3 -m rxlab fuzz -n 2000 --seed 1

# tests (50, includes a headless-Chromium check of the page's JS VM)
python3 -m unittest discover -s tests
```

Python API mirrors `re` on the supported subset:

```python
import rxlab
m = rxlab.compile(r'(\d+)-(\d+)').search('call 555-1234')
m.span(), m.groups()        # (5, 13), ('555', '1234')
rxlab.compile(r'ab*').dfa().fullmatch('abbb')   # True — DFA fast path
```

## Features shipped

**Required**

1. **Parser + Thompson NFA** — literals, `.`, escapes (`\d \w \s \D \W \S`,
   `\xHH`, control escapes), character classes with ranges & negation,
   greedy *and lazy* quantifiers (`* + ? {m} {m,} {m,n}` + `?`-suffix),
   alternation, capturing/non-capturing groups, anchors `^ $`, word
   boundaries `\b \B`; positioned, specific error messages (try `\1` or
   `(?=`) and `re`-faithful literal-brace handling.
2. **Pike VM** — `match` / `fullmatch` / `search` / `finditer` / `findall`
   with leftmost-greedy capture semantics, the post-3.7 empty-match
   "must-advance" rule, and a `pos` argument; **differentially fuzzed
   against `re` (thousands of random patterns, zero diffs)**; linear-time,
   immune to catastrophic backtracking by construction.
3. **DFA pipeline** — alphabet partitioning into character classes, subset
   construction with positional anchor handling, **Hopcroft minimization**
   (cross-checked against an independent Moore implementation in tests);
   `(a|b)*abb` → the textbook 4-state minimal DFA; state counts reported
   (`NFA → subset → minimal`).
4. **Interactive visualizer** — one self-contained HTML file per pattern:
   SVG renderings of both the NFA program and the minimized DFA, an input
   tape with cursor, transport controls + keyboard shortcuts, live-thread
   highlighting in priority order, capture-group table, DFA-agreement
   readout, legend. The page embeds a JS mirror of the Pike VM —
   *proven equivalent to the Python engine by an automated headless-Chromium
   test*.

**Stretch (all three shipped)**

5. **Explain mode** — indented plain-English pattern breakdown.
6. **Sample generator** — seedable random matching strings, rejection-
   sampled through the engine so anchors are honored; flags likely-
   unsatisfiable patterns (`a\bb`).
7. **Differential fuzzer** — first-class `fuzz` command checking all five
   API modes plus DFA≡NFA equivalence against `re`, non-zero exit on
   divergence.

**Deliberate scope decisions** (see REVIEW.md for the full list): ASCII
class semantics; no backreferences/lookarounds (strictly regular — that's
what makes the DFA and the complexity guarantee possible); DFA engine
declines `\b`/`\B` with a clear error; lazy quantifiers over *nullable*
bodies nested in another quantifier may differ from backtrackers (same
corner where RE2 differs from PCRE).

## Why this today

Yesterday was a world generator — today I wanted classic computer science
made tangible. Everyone uses regexes; almost nobody has *watched* one run.
Building the whole pipeline honestly (priority-ordered threads, capture
slots, epsilon-closure with anchors, alphabet partitioning, minimization)
is the best kind of engineering workout, and the payoff is a teaching tool
I'd actually use: the difference between "regexes are spooky" and "oh, it's
just threads walking a graph" is one `play` button.

## Where a human could take this next

- **Counted-repeat instructions** instead of macro-expansion (`a{1000}`
  currently costs 1000 states), and an `x*` → reverse-DFA "leftmost-longest
  POSIX" mode.
- **DFA `\b` support** via the (prev-char-class × state) product
  construction, and lazy/online DFA construction with an LRU state cache —
  the RE2 trick — for big patterns.
- **Visualizer**: show capture-slot writes on the tape, render the *path*
  the winning thread took after a match, shareable URLs (pattern in the
  fragment), side-by-side NFA/DFA stepping.
- **More syntax**: named groups, `(?i)` flags, lookarounds on the NFA
  engine (they keep it finite-state if bounded).
- Package it: `pip install regexlab`, `regexlab serve` for a local
  playground, embed pages in docs/blogs (they're single files already).
