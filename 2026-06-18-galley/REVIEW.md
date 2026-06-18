# Galley — Adversarial Review (Phase 3)

I attacked my own build as a hostile reviewer: edge cases, fake features, lazy
shortcuts, and quality defects. Findings below, each with the fix applied.

## Method

- Edge-case sweep: empty string, single word, a 45-letter unhyphenatable word,
  1 pt measure, punctuation, non-ASCII, numbers, embedded hyphens, newlines,
  whitespace-only, huge measure. **No crashes; round-trip held in all cases.**
- 2,000-paragraph differential fuzz of the Knuth–Plass DP against a brute-force
  optimum: **0 mismatches** (the core algorithm is provably optimal).
- Targeted probes of looseness, hyphenation reach, river detection, and the CLI
  surface.

## Findings & fixes

### 1. (CRITICAL — fake feature) `looseness` parameter did nothing
`break_paragraph(..., looseness=±1)` returned the *same* line count in every
test, even with wide tolerance and paragraphs where N±1-line solutions exist.
Root cause: the DP keeps only the best node **per fitness class** at each
breakpoint, which collapses paths of different line counts into one — so the
final active list never contains alternative-length solutions for the
post-hoc chooser to pick from. Shipping a parameter that silently has no effect
is exactly the "mocked logic pretending to be real" the brief forbids.
**Fix:** removed `looseness` and the dead `_choose_active` branch entirely; the
breaker now always returns the global demerit minimum. Honest and correct.
(Per the brief, a removed feature is replaced by equal-size work — see the
*punctuation-aware hyphenation* upgrade in #4, which materially improves real
output.)

### 2. (bug) Empty `--text ""` silently typeset the built-in sample
`_read_text` used a truthiness check (`if args.text:`), so an explicit empty
string fell through to the sample paragraph. **Fix:** distinguish `None` from
`""` with explicit `is not None` checks; an empty document now renders empty.

### 3. (bug) Overfull ASCII lines were truncated in the `break` CLI
`"|" + l.ljust(width)[:width] + "|"` chopped any line longer than the measure
(an unbreakable long word), **hiding text** and misrepresenting the result as
fitting. **Fix:** never truncate; overfull lines now overflow the right border
and are marked with a `▸` so the defect is visible, not hidden.

### 4. (quality) Words with attached punctuation never hyphenated
`_is_hyphenatable` required `word.isalpha()`, so `beautiful,` `castle,` `much,`
— extremely common in real prose — were never split. In the sample paragraph
this suppressed almost all hyphenation. **Fix:** hyphenate the alphabetic
*core* of a token while keeping leading/trailing punctuation attached to the
adjacent fragment, so `beautiful,` can break as `beau-ti-ful,`.

### 5. (quality) River detector flagged everything
At a 1.5×space threshold it reported 7 "rivers" in the optimal paragraph — the
*same* count as greedy — so it carried no signal. Justified text always has
loosely-aligned gaps. **Fix:** tightened the alignment threshold to 0.4×space
and required each participating gap to be at least the natural space wide, so
only genuine vertical channels register; optimal text now shows materially
fewer rivers than greedy.

### 6. (verified OK, no change needed)
- SVG/HTML escaping (`<`, `&`, `"`) via `html.escape(quote=True)`.
- Non-ASCII characters fall back to a sensible average advance width and skip
  hyphenation without error.
- Round-trip integrity (lines tile the node list; words reproduce exactly)
  holds across every adversarial input.
- Embedded font metrics are real Adobe AFM values; JS playground breaker is a
  faithful port (parity gated in Phase 5).

## Post-fix gate
A fresh re-run of the edge-case sweep, the differential fuzz, and the targeted
probes hits **zero** of the issues above.
