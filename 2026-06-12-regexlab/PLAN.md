# RegexLab — a regex engine you can see think

## Concept

A complete regular-expression engine written from scratch in pure Python 3
stdlib — lexer, parser, Thompson NFA construction, Pike-VM simulation with
capture groups, subset-construction DFA with Hopcroft minimization — plus an
**interactive single-file HTML visualizer**: type a test string in the browser
and step through the engine's execution character by character, watching the
active automaton states light up. Think "regex101, offline, showing you the
real machine instead of a syntax highlighter."

## Why it's interesting

Everyone uses regexes; almost nobody has watched one run. The classic
theory (NFA ≃ DFA ≃ regular languages) is beautiful but usually taught with
chalk. Building the whole pipeline forces honest engineering: leftmost-greedy
capture semantics, lazy quantifiers, epsilon-closure subtleties, DFA blowup,
minimization. And the visualizer turns it into a product, not a homework
exercise: a tool you'd actually open to debug a regex or teach automata.

## Architecture

```
pattern string
   │  lexer + recursive-descent parser
   ▼
AST (nodes: Lit, Class, Dot, Anchor, Concat, Alt, Repeat, Group)
   │  Thompson construction
   ▼
NFA (states, ε-moves, char-class edges, capture tags)
   ├─ Pike VM  ──► match / search / findall / finditer with capture groups
   │               and a recorded step-by-step TRACE
   ├─ subset construction ──► DFA ──► Hopcroft minimization
   │                                   (fast boolean fullmatch path)
   └─ layout + SVG emitter ──► self-contained interactive HTML
                                (JS Pike VM runs the same NFA as data)
```

- `rxlab/lexer.py` — tokenizer
- `rxlab/parser.py` — AST + recursive-descent parser with good error messages
- `rxlab/nfa.py` — Thompson construction; NFA as plain data
- `rxlab/vm.py` — Pike VM: thread list, priority order, capture slots, trace recording
- `rxlab/dfa.py` — subset construction, Hopcroft minimization, DFA matcher
- `rxlab/explain.py` — AST → plain-English explanation
- `rxlab/gen.py` — AST → random sample strings that match
- `rxlab/viz.py` — automaton layout + single-file HTML/SVG/JS emitter
- `rxlab/cli.py` — `python3 -m rxlab <cmd>`
- `tests/` — unit tests + differential fuzzer vs Python's `re`

## Supported syntax (the "RegexLab subset")

Literals, `.`, escapes (`\d \D \w \W \s \S \n \t` + punctuation escapes),
character classes `[a-z0-9_]` / `[^…]` with ranges and escapes, quantifiers
`* + ? {m} {m,} {m,n}` each with lazy variant (`*?` etc.), alternation `|`,
capturing groups `( )`, non-capturing `(?: )`, anchors `^ $`, word boundaries
`\b \B`, backreference-free (regular languages only — that's the point; DFA
compilation requires it).

## Features

### Required
1. **Full parser + Thompson NFA** for the syntax above, with precise error
   messages (position + reason) for malformed patterns.
2. **Pike VM matcher** — `match`, `fullmatch`, `search`, `findall`,
   `finditer` with correct leftmost / greedy / lazy semantics and numbered
   capture groups; agrees with Python `re` on the supported subset.
3. **DFA pipeline** — subset construction + Hopcroft minimization;
   `fullmatch` via DFA agrees with the NFA; CLI reports state counts
   (NFA → DFA → minimal DFA).
4. **Interactive HTML visualizer** — `rxlab viz PATTERN -o page.html` emits a
   single self-contained file: SVG automaton (NFA or DFA view), a test-string
   input, and step/play controls that highlight active states, consumed
   input, and thread captures as the engine runs (JS Pike VM executing the
   same NFA serialized as JSON).

### Stretch
5. **Explain mode** — `rxlab explain PATTERN` prints an indented
   plain-English breakdown of the pattern.
6. **Sample generator** — `rxlab gen PATTERN -n 10` produces random strings
   that match (seedable, with max-repeat cap), verified by feeding them back
   through the engine.
7. **Differential fuzzer** — `rxlab fuzz` generates random patterns + inputs
   in the supported subset and diffs our engine against Python's `re`
   (also doubles as verification).

## Verification plan

- `tests/test_*.py` (unittest): parser errors, AST shapes, VM semantics
  (greedy/lazy/captures/anchors), DFA ≡ NFA on a corpus, minimization
  counts, explain/gen round-trips.
- Differential fuzz: hundreds of random (pattern, input) pairs vs `re`.
- Node + jsdom smoke test: load generated HTML, drive the JS stepper,
  assert states highlight and verdict matches Python engine.
- `demo.sh` exercising every CLI command.
