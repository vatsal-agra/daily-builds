# Cascade

A from-scratch HTML/CSS layout and rendering engine. See [PLAN.md](PLAN.md)
for the concept, architecture, and full feature list.

**Status: Phase 2 (core build) complete.** All four required features work
end-to-end:

1. HTML parser (`cascade/html_parser.py`) — tokenizer + tree-construction
   with implicit tag closing and malformed-markup recovery.
2. CSS parser + cascade (`cascade/css_parser.py`, `cascade/cascade.py`) —
   real selector grammar, specificity, `!important`, inheritance.
3. Layout engine (`cascade/layout.py`) — box model, block formatting
   context with margin collapsing, inline formatting context with line
   breaking, text-align, and float layout.
4. Paint (`cascade/paint.py`) — SVG renderer with backgrounds, per-side
   borders, and positioned text.

## Try it

```
python3 cli.py render testpages/01_box_model.html -o /tmp/out.svg
python3 cli.py dump-boxes testpages/04_floats.html
```

## Differential verification against real Chromium

This sandbox has headless Chromium pre-installed. `oracle/run_diff.py`
renders every `testpages/*.html` fixture with Cascade's own engine *and*
with real Chromium (via `oracle/diff.cjs` + Playwright), then diffs every
element's `getBoundingClientRect()`-equivalent geometry:

```
python3 oracle/run_diff.py testpages
```

Current result: **7/7 test pages, 0 mismatches** against real Chromium
(box model, margin collapsing, text wrapping/alignment, floats + clear,
inline-block shrink-to-fit, cascade/specificity, and margin:auto
centering).

Next: adversarial review (Phase 3), stretch features + polish (Phase 4),
full verification pass (Phase 5), ship (Phase 6).
