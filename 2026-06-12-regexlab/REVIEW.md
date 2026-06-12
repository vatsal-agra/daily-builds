# Adversarial review — RegexLab (Phase 3)

Hostile pass over the phase-2 build: parser/VM/DFA semantics fuzzed and
edge-cased against `re`, visualizer attacked in headless Chromium, CLI poked
with malformed input. Findings below; every **Fix** was applied and is
covered by the phase-5 test suite.

## Bugs found and fixed

1. **`search` died instead of scanning past dead spots.**
   `\bcat\b` on `"the cat sat"` returned no match: the VM broke out of its
   loop when the live-thread list went empty, but in search mode it must
   keep seeding threads at later positions. *Fix:* only break on an empty
   thread list outside search mode (both the Python VM and its JS mirror).

2. **`\D` / `\W` / `\S` outside classes lost their negation.**
   The escape handler returned a "negclass" tag the atom builder ignored,
   so `\D` matched digits. *Fix:* propagate the negation flag.

3. **`{m,n}` brace parsing was wrong on `{,}` / `{}` forms.**
   Convoluted condition both rejected valid `{,5}` and mis-handled `{}`.
   *Fix:* rewrote the brace parser; `{,5}`≡`{0,5}`, `{}`/`{,}`/`{2` are
   literals, exactly as in `re`.

4. **`findall`/`finditer` diverged from `re` on empty matches.**
   We advanced by one after any empty match; Python ≥3.7 instead *retries
   the same position banning the empty match*, so `(?:\w)*?` on `"a1"`
   yields `['', 'a', '', '1', '']`, not `['', '', '']`. *Fix:* implemented
   the must-advance rule (`ban_empty_at` in the VM); finditer fuzz is now
   diff-free over 5,000 random patterns.

5. **`\B` matched in the empty string; `re` says it never does.**
   *Fix:* mimic the quirk in both VMs.

6. **`[\d-x]` silently treated `-` as a literal; `re` raises
   "bad character range".** *Fix:* raise the same error (while keeping
   `[\d-]` valid).

7. **`(?` at end of pattern gave a confusing "unsupported group
   extension '(?'" message.** *Fix:* now reports "unexpected end of
   pattern", like `re`.

8. **Broken expression in the visualizer's `layerLayout`** (leftover
   editing junk computing the SVG width). *Fix:* corrected; plus removed a
   dead `state.step` assignment in `recompute()`.

9. **`dfa --table` printed raw control/astral codepoints** (e.g. literal
   `chr(0x10FFFF)`) in range labels. *Fix:* shared `format_ranges` helper
   with `\xNN`/`U+XXXX` escapes, used by the CLI table.

10. **Visualizer UX: every keystroke jumped the stepper to the final
    step**, so you always had to press ⏮ before stepping. *Fix:* new input
    resets to step 0 (the verdict panel is precomputed and visible either
    way).

11. **"DFA verdict" line was unlabeled apples-to-oranges** next to a
    search-mode result. *Fix:* now reads "DFA fullmatch: accept/reject" and
    in fullmatch mode explicitly confirms agreement with the NFA.

12. **CLI couldn't take patterns starting with `-`** (argparse eats them).
    *Fix:* documented `--` separator in `--help` epilog and README; argparse
    handles it natively (`rxlab search -- '-\d+' 'x-42'`).

## Deliberate divergences from `re` (documented, not bugs)

- **Lazy quantifiers over empty-matchable bodies inside another
  quantifier** (e.g. `(?:(?:\w)*?)*`) can match more than `re`, because a
  Pike VM resolves empty-loop iterations by thread priority while a
  backtracker stops a loop at the first empty iteration. RE2 diverges from
  PCRE in the same corner. The differential fuzzer skips quantifying
  nullable bodies for this reason.
- **ASCII semantics** for `\d \w \s` (compare against `re.ASCII`).
- **No backreferences, lookarounds, or named groups** — strictly regular by
  design (that's what makes the DFA compilation and O(n·m) guarantee
  possible); all three fail with explanatory errors.
- **DFA engine rejects `\b`/`\B`** with a clear error (context-dependent
  assertions don't fit positional subset construction); the NFA engine
  handles them.

## Attacks that did NOT find problems

- 5,000-pattern differential fuzz vs `re` across search/match/fullmatch/
  finditer/findall + DFA≡NFA equivalence: zero diffs after fixes.
- ReDoS: `(a+)+$` over 40 `a`s + `X` answers in <1 ms (backtrackers take
  minutes); engine is structurally immune to catastrophic backtracking.
- XSS: pattern `a</script><img onerror=…>` and HTML in test strings render
  inert (JSON `</`-escaping + `textContent`/escaped interpolation).
- Parser error battery (16 malformed patterns) all produce positioned
  errors, no crashes; `a{2,1}`, `[z-a]`, `\x1`, `a**`, `^*` etc. match
  `re`'s accept/reject decisions.
- Unicode: literals, ranges (`[α-ω]`), astral chars (`🎉`) — codepoint
  semantics agree with Python on both engines and in the browser JS
  (which iterates real codepoints, not UTF-16 units).
- Anchors/`^$` in DFA fullmatch (`^$`, `a$b`, `^a|b$`) correct; `a$b`
  correctly compiles to a single rejecting state.
